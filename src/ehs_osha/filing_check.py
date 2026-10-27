"""Evaluate one Form 300A filing against the shared JSON plausibility rules.

The rules live in ``plausibility_rules.json`` and are evaluated by this module
and by ``docs/filing_check.js``. ``tests/test_filing_check_parity.py`` checks
that both agree with each other and with the vectorised
:func:`ehs_osha.quality.apply_screen` that produces the published results.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

SPEC_PATH = Path(__file__).with_name("plausibility_rules.json")


def load_rules(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the rule spec from JSON."""
    return json.loads(Path(path or SPEC_PATH).read_text(encoding="utf-8"))


def _num(value: Any) -> float:
    """Return value as a float, or NaN when missing or not numeric."""
    if value is None or isinstance(value, bool):
        return math.nan
    try:
        x = float(value)
    except (TypeError, ValueError):
        return math.nan
    return x if math.isfinite(x) else math.nan


def _eval_flag(flag: Mapping[str, Any], rec: Mapping[str, Any], params: Mapping[str, Any],
               cases: float) -> bool:
    kind = flag["kind"]
    if kind == "missing_or_at_most":
        x = _num(rec.get(flag["field"]))
        return math.isnan(x) or x <= flag["value"]
    if kind == "missing_or_below":
        x = _num(rec.get(flag["field"]))
        return math.isnan(x) or x < flag["value"]
    if kind == "negative_or_incomplete_cases":
        vals = [_num(rec.get(f)) for f in flag["fields"]]
        return math.isnan(cases) or any(v < 0 for v in vals if not math.isnan(v))
    if kind in ("ratio_above", "ratio_below"):
        num = _num(rec.get(flag["numerator"]))
        den = _num(rec.get(flag["denominator"]))
        if math.isnan(num) or math.isnan(den) or not den > flag["denominator_must_exceed"]:
            return False
        ratio = num / den
        bound = params[flag["param"]]
        return ratio > bound if kind == "ratio_above" else ratio < bound
    if kind == "checkbox_contradiction":
        x = _num(rec.get(flag["field"]))
        if math.isnan(x) or math.isnan(cases):
            return False
        for c in flag["contradictions"]:
            if x == c["value"] and ((c["when"] == "cases_positive" and cases > 0)
                                    or (c["when"] == "cases_zero" and cases == 0)):
                return True
        return False
    raise ValueError(f"unknown rule kind: {kind}")


def check_filing(record: Mapping[str, Any], rules: Optional[Mapping[str, Any]] = None,
                 **overrides: float) -> Dict[str, Any]:
    """Check one filing.

    Args:
        record: Mapping with the Form 300A fields named in the rules.
        rules: Rule spec; defaults to the packaged one.
        **overrides: Replacement values for entries of ``params``.

    Returns:
        ``{"flags": {id: bool}, "implausible": bool, "messages": [str]}``.
    """
    spec = rules or load_rules()
    params = {**spec["params"], **overrides}
    parts = [_num(record.get(f)) for f in spec["case_fields"]]
    cases = math.nan if any(math.isnan(p) for p in parts) else sum(parts)
    flags: Dict[str, bool] = {}
    implausible = False
    messages = []
    for flag in spec["flags"]:
        hit = _eval_flag(flag, record, params, cases)
        flags[flag["id"]] = hit
        counts = flag["counts_toward_implausible"]
        if isinstance(counts, str):
            counts = bool(params[counts.split(":", 1)[1]])
        if hit:
            messages.append(flag["message"])
            implausible = implausible or counts
    return {"flags": flags, "implausible": implausible, "messages": messages}
