"""Data expectations as code: declarative checks over the committed outputs.

``expectations.json`` lists checks; each has an ``id``, a ``severity``
(``error`` or ``warn``), a ``rationale`` and a ``scope``:

* ``structural``: must hold for any run of the pipeline, including a run on the
  synthetic fixture (schema, nulls, bounds, accounting identities);
* ``committed``: pins a property of the committed real-data outputs (exact row
  counts, the 2016-2024 year set, the default screen's counts).

A table that does not exist is a failure, except when the runner is told to
allow missing tables (used for fixture runs, where some stages are skipped);
those expectations are reported as ``skip``.

The process exits nonzero if any ``error`` expectation fails. ``warn`` failures
are reported in the document but only fail the run with ``--strict``.

Check kinds (parameters in parentheses; ``where`` restricts rows by equality):

``rows`` (min, max, equals); ``columns`` (columns); ``not_null`` (columns,
where); ``range`` (columns, min, max, min_ref, max_ref, where); ``unique``
(columns); ``years`` (column, min, max); ``value_set`` (column, values);
``value_in`` (column, values); ``col_le`` (left, right); ``sum_ref`` (column,
ref, where, where_prefix, rel_tol); ``sum_columns`` (columns, equals);
``ratio`` (num, den, equals, scale, rel_tol); ``linear`` (terms, equals);
``monotone_row`` (columns); ``monotone_col`` (column, by, direction);
``group_sum`` (group_by, column, equals); ``lookup`` (column, where, ref or
equals, rel_tol); ``scalar`` (path, min, max, max_ref, equals_ref, equals);
``scalar_diff`` (a, b, equals_ref).

A ``ref`` is ``{"summary": "a.b"}``, ``{"summary_diff": ["a.b", "c.d"]}`` or
``{"table": name, "column": c, "agg": "sum"|"first", "where": {...}}``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SPEC = Path(__file__).with_name("expectations.json")
TABLES = ROOT / "outputs" / "tables"
SUMMARY = ROOT / "outputs" / "summary.json"
DOC = ROOT / "docs" / "DATA_HEALTH.md"


@dataclass
class Result:
    """Outcome of one expectation."""

    id: str
    severity: str
    status: str  # pass | fail | skip
    observed: str


class MissingTable(Exception):
    """Raised when an expectation needs a table that is not on disk."""


class Context:
    """Lazy access to tables and the summary for one run."""

    def __init__(self, tables: Path, summary: Path) -> None:
        self.tables = Path(tables)
        self.summary_path = Path(summary)
        self._cache: Dict[str, pd.DataFrame] = {}
        self._summary: Optional[Dict[str, Any]] = None

    def table(self, name: str) -> pd.DataFrame:
        if name not in self._cache:
            p = self.tables / f"{name}.csv"
            if not p.exists():
                raise MissingTable(name)
            self._cache[name] = pd.read_csv(p)
        return self._cache[name]

    def summary(self) -> Dict[str, Any]:
        if self._summary is None:
            if not self.summary_path.exists():
                raise MissingTable("summary.json")
            self._summary = json.loads(self.summary_path.read_text(encoding="utf-8"))
        return self._summary

    def path(self, dotted: str) -> Any:
        cur: Any = self.summary()
        for part in dotted.split("."):
            cur = cur[part]
        return cur

    def ref(self, ref: Dict[str, Any]) -> float:
        if "summary" in ref:
            return float(self.path(ref["summary"]))
        if "summary_diff" in ref:
            a, b = ref["summary_diff"]
            return float(self.path(a)) - float(self.path(b))
        df = _where(self.table(ref["table"]), ref.get("where"))
        col = df[ref["column"]]
        return float(col.sum() if ref.get("agg", "first") == "sum" else col.iloc[0])


def _where(df: pd.DataFrame, where: Optional[Dict[str, Any]], prefix: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    for k, v in (where or {}).items():
        df = df[df[k] == v]
    for k, v in (prefix or {}).items():
        df = df[df[k].astype(str).str.startswith(v)]
    return df


def _fmt(x: Any) -> str:
    if isinstance(x, (bool,)):
        return str(x)
    if isinstance(x, (int,)) or (isinstance(x, float) and x == int(x) and abs(x) < 1e15):
        return f"{int(x):,}"
    if isinstance(x, float):
        return f"{x:.6g}"
    return str(x)


def _close(a: float, b: float, rel: float) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=rel * 1e-3)


def _rows(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    n = len(ctx.table(e["table"]))
    ok = True
    if "equals" in e:
        ok &= n == e["equals"]
    if "min" in e:
        ok &= n >= e["min"]
    if "max" in e:
        ok &= n <= e["max"]
    return ok, f"{n:,} rows"


def _columns(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    have = set(ctx.table(e["table"]).columns)
    missing = [c for c in e["columns"] if c not in have]
    return not missing, "missing " + ", ".join(missing) if missing else f"{len(e['columns'])} columns present"


def _not_null(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    df = _where(ctx.table(e["table"]), e.get("where"))
    bad = {c: int(df[c].isna().sum()) for c in e["columns"] if df[c].isna().any()}
    return not bad, ("nulls: " + ", ".join(f"{c}={n}" for c, n in bad.items())) if bad else f"0 nulls in {len(df):,} rows"


def _range(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    df = _where(ctx.table(e["table"]), e.get("where"))
    lo = e.get("min")
    hi = e.get("max")
    if "min_ref" in e:
        lo = ctx.ref(e["min_ref"])
    if "max_ref" in e:
        hi = ctx.ref(e["max_ref"])
    bad = 0
    seen_lo, seen_hi = math.inf, -math.inf
    for c in e["columns"]:
        v = df[c].dropna().astype(float)
        if v.empty:
            continue
        seen_lo, seen_hi = min(seen_lo, float(v.min())), max(seen_hi, float(v.max()))
        if lo is not None:
            bad += int((v < lo).sum())
        if hi is not None:
            bad += int((v > hi).sum())
    span = "no values" if seen_lo == math.inf else f"observed {_fmt(seen_lo)} to {_fmt(seen_hi)}"
    return bad == 0, (f"{bad} values outside bounds; " if bad else "") + span


def _unique(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    d = int(ctx.table(e["table"]).duplicated(subset=e["columns"]).sum())
    return d == 0, f"{d} duplicate keys"


def _years(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    # Non-numeric labels (for example a "pooled" row) are not years and are ignored.
    v = pd.to_numeric(ctx.table(e["table"])[e["column"]], errors="coerce").dropna()
    bad = int(((v < e["min"]) | (v > e["max"]) | (v != v.round())).sum())
    return bad == 0, f"{bad} outside {e['min']}-{e['max']}; observed {_fmt(float(v.min()))}-{_fmt(float(v.max()))}"


def _value_set(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    got = sorted({_norm(x) for x in ctx.table(e["table"])[e["column"]].dropna()})
    want = sorted({_norm(x) for x in e["values"]})
    return got == want, f"{len(got)} distinct values" if got == want else f"got {got}, want {want}"


def _value_in(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    got = {_norm(x) for x in ctx.table(e["table"])[e["column"]].dropna()}
    extra = sorted(got - {_norm(x) for x in e["values"]})
    return not extra, f"unexpected {extra}" if extra else f"{len(got)} distinct values, all allowed"


def _norm(x: Any) -> Any:
    return int(x) if isinstance(x, float) and x == int(x) else x


def _col_le(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    df = ctx.table(e["table"])[[e["left"], e["right"]]].dropna()
    bad = int((df[e["left"]] > df[e["right"]] * (1 + 1e-12) + 1e-12).sum())
    return bad == 0, f"{bad} rows violate {e['left']} <= {e['right']}"


def _sum_ref(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    df = _where(ctx.table(e["table"]), e.get("where"), e.get("where_prefix"))
    got = float(df[e["column"]].sum())
    want = ctx.ref(e["ref"])
    return _close(got, want, e.get("rel_tol", 1e-9)), f"sum {_fmt(got)} vs reference {_fmt(want)}"


def _sum_columns(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    df = ctx.table(e["table"])
    diff = (df[e["columns"]].sum(axis=1) - df[e["equals"]]).abs()
    bad = int((diff > 1e-9 * df[e["equals"]].abs().clip(lower=1)).sum())
    return bad == 0, f"{bad} rows where components differ from {e['equals']}"


def _ratio(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    df = ctx.table(e["table"])[[e["num"], e["den"], e["equals"]]].dropna()
    df = df[df[e["den"]] != 0]
    want = df[e["num"]] * e.get("scale", 1) / df[e["den"]]
    tol = e.get("rel_tol", 1e-6)
    bad = int((~((want - df[e["equals"]]).abs() <= tol * want.abs().clip(lower=1e-12) + 1e-12)).sum())
    return bad == 0, f"{bad} of {len(df):,} rows disagree with {e['num']} / {e['den']}"


def _linear(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    df = ctx.table(e["table"])
    total = sum(df[c] * w for c, w in e["terms"].items())
    diff = (total - df[e["equals"]]).abs().dropna()
    bad = int((diff > 1e-6 * df[e["equals"]].abs().loc[diff.index].clip(lower=1)).sum())
    return bad == 0, f"{bad} of {len(diff):,} rows disagree"


def _monotone_row(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    df = ctx.table(e["table"])[e["columns"]].dropna()
    ok = pd.Series(True, index=df.index)
    for a, b in zip(e["columns"], e["columns"][1:]):
        ok &= df[a] <= df[b] + 1e-12
    return bool(ok.all()), f"{int((~ok).sum())} rows not ordered {' <= '.join(e['columns'])}"


def _monotone_col(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    df = ctx.table(e["table"]).sort_values(e["by"])
    d = df[e["column"]].diff().dropna()
    bad = int((d < -1e-12).sum())
    return bad == 0, f"{bad} decreases when ordered by {e['by']}"


def _group_sum(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    g = ctx.table(e["table"]).groupby(e["group_by"])[e["column"]].apply(lambda s: s.astype(int).sum())
    bad = int((g != e["equals"]).sum())
    return bad == 0, f"{bad} of {len(g):,} groups where sum of {e['column']} is not {e['equals']}"


def _lookup(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    df = _where(ctx.table(e["table"]), e.get("where"))
    if df.empty:
        return False, "no matching row"
    got = float(df[e["column"]].iloc[0])
    want = float(e["equals"]) if "equals" in e else ctx.ref(e["ref"])
    return _close(got, want, e.get("rel_tol", 1e-9)), f"{_fmt(got)} vs reference {_fmt(want)}"


def _scalar(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    v = ctx.path(e["path"])
    if "equals" in e:
        return v == e["equals"], f"{v}"
    x = float(v)
    ok = True
    if "min" in e:
        ok &= x >= e["min"]
    if "max" in e:
        ok &= x <= e["max"]
    if "max_ref" in e:
        ok &= x <= ctx.ref(e["max_ref"])
    if "equals_ref" in e:
        ok &= _close(x, ctx.ref(e["equals_ref"]), 1e-9)
    return bool(ok), _fmt(x)


def _scalar_diff(ctx: Context, e: Dict[str, Any]) -> "tuple[bool, str]":
    got = float(ctx.path(e["a"])) - float(ctx.path(e["b"]))
    want = ctx.ref(e["equals_ref"])
    return _close(got, want, 1e-9), f"{_fmt(got)} vs reference {_fmt(want)}"


CHECKS: Dict[str, Callable[[Context, Dict[str, Any]], "tuple[bool, str]"]] = {
    "rows": _rows, "columns": _columns, "not_null": _not_null, "range": _range,
    "unique": _unique, "years": _years, "value_set": _value_set, "value_in": _value_in,
    "col_le": _col_le, "sum_ref": _sum_ref, "sum_columns": _sum_columns, "ratio": _ratio,
    "linear": _linear, "monotone_row": _monotone_row, "monotone_col": _monotone_col,
    "group_sum": _group_sum, "lookup": _lookup, "scalar": _scalar, "scalar_diff": _scalar_diff,
}

REQUIRED = ("id", "severity", "scope", "check", "target", "rationale")


def load_spec(path: Path = SPEC) -> List[Dict[str, Any]]:
    """Read and sanity-check the expectation list."""
    items = json.loads(path.read_text(encoding="utf-8"))["expectations"]
    ids = set()
    for e in items:
        for k in REQUIRED:
            if k not in e:
                raise ValueError(f"expectation {e.get('id')} lacks {k}")
        if e["severity"] not in ("error", "warn") or e["scope"] not in ("structural", "committed"):
            raise ValueError(f"expectation {e['id']} has bad severity or scope")
        if e["check"] not in CHECKS:
            raise ValueError(f"expectation {e['id']} has unknown check {e['check']}")
        if e["id"] in ids:
            raise ValueError(f"duplicate expectation id {e['id']}")
        ids.add(e["id"])
    return items


def run_expectations(
    tables: Path = TABLES,
    summary: Path = SUMMARY,
    spec: Optional[List[Dict[str, Any]]] = None,
    *,
    structural_only: bool = False,
    allow_missing: bool = False,
) -> List[Result]:
    """Evaluate expectations and return one :class:`Result` each."""
    items = spec if spec is not None else load_spec()
    ctx = Context(tables, summary)
    out: List[Result] = []
    for e in items:
        if structural_only and e["scope"] != "structural":
            continue
        ee = dict(e)
        ee["table"] = e["target"] if e["target"] != "summary" else None
        try:
            ok, observed = CHECKS[e["check"]](ctx, ee)
            status = "pass" if ok else "fail"
        except MissingTable as m:
            status, observed = ("skip", f"{m} not present") if allow_missing else ("fail", f"{m} not present")
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            status, observed = "fail", f"error evaluating: {type(exc).__name__}: {exc}"
        out.append(Result(e["id"], e["severity"], status, observed))
    return out


def failed(results: List[Result], strict: bool = False) -> List[Result]:
    """Failures that should fail the run."""
    return [r for r in results if r.status == "fail" and (strict or r.severity == "error")]


def render(results: List[Result], spec: List[Dict[str, Any]]) -> str:
    """Render docs/DATA_HEALTH.md (deterministic)."""
    by_id = {e["id"]: e for e in spec}
    n = len(results)
    npass = sum(r.status == "pass" for r in results)
    nfail = sum(r.status == "fail" for r in results)
    targets = sorted({by_id[r.id]["target"] for r in results})
    out = [
        "# Data health",
        "",
        "Generated by `python3 -m ehs_osha.health` from `src/ehs_osha/health/expectations.json` "
        "over the committed `outputs/tables/*.csv` and `outputs/summary.json`. Do not edit by hand: "
        "`tests/test_health.py` fails if this file differs from the runner output.",
        "",
        "Each expectation has an id, a severity (`error` fails the run, `warn` is reported), a rationale "
        "and a check. Observed values are read from the committed outputs at generation time.",
        "",
        f"**{npass} of {n} expectations pass** across {len(targets)} targets "
        f"({nfail} failing). Error severity: {sum(by_id[r.id]['severity'] == 'error' for r in results)}; "
        f"warn severity: {sum(by_id[r.id]['severity'] == 'warn' for r in results)}.",
        "",
    ]
    if nfail:
        out += ["## Failing", "", "| Id | Severity | Observed |", "|---|---|---|"]
        out += [f"| `{r.id}` | {r.severity} | {r.observed} |" for r in results if r.status == "fail"]
        out.append("")
    out += ["## By target", "", "| Target | Expectations | Passing |", "|---|---|---|"]
    for t in targets:
        rs = [r for r in results if by_id[r.id]["target"] == t]
        out.append(f"| `{t}` | {len(rs)} | {sum(r.status == 'pass' for r in rs)} |")
    out.append("")
    for t in targets:
        out += [f"## {t}", "", "| Id | Sev | Check | Rationale | Observed | Result |", "|---|---|---|---|---|---|"]
        for r in results:
            e = by_id[r.id]
            if e["target"] == t:
                obs = r.observed.replace("|", "/")
                out.append(f"| `{r.id}` | {r.severity} | {e['check']} | {e['rationale']} | {obs} | {r.status.upper()} |")
        out.append("")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    """Run expectations, print failures, optionally write the doc."""
    ap = argparse.ArgumentParser(description="Run data expectations over the pipeline outputs.")
    ap.add_argument("--tables", default=str(TABLES))
    ap.add_argument("--summary", default=str(SUMMARY))
    ap.add_argument("--doc", default=str(DOC), help="where to write DATA_HEALTH.md ('' to skip)")
    ap.add_argument("--structural-only", action="store_true")
    ap.add_argument("--allow-missing", action="store_true")
    ap.add_argument("--strict", action="store_true", help="warn failures also fail the run")
    args = ap.parse_args(argv)
    spec = load_spec()
    results = run_expectations(
        Path(args.tables), Path(args.summary), spec,
        structural_only=args.structural_only, allow_missing=args.allow_missing,
    )
    bad = failed(results, args.strict)
    for r in results:
        if r.status == "fail":
            print(f"FAIL [{r.severity}] {r.id}: {r.observed}")
    print(f"{sum(r.status == 'pass' for r in results)}/{len(results)} expectations pass")
    if args.doc:
        Path(args.doc).write_text(render(results, spec), encoding="utf-8")
        print(f"wrote {args.doc}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
