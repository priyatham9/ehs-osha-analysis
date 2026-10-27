"""Tests for the unsubmitted manuscript draft in ``docs/manuscript/``.

The manuscript carries no number that is not registered in its Appendix A,
and every Appendix A row names a committed source file and a locator that this
module evaluates against that file. A number therefore fails here if the text
drifts from a table, if a table is regenerated with a different value, if a
number in the prose is unregistered, or if a registered number is unused.
"""

from __future__ import annotations

import json
import re
import unittest
from decimal import ROUND_HALF_UP, Decimal

import _context
import pandas as pd

ROOT = _context.ROOT
MANUSCRIPT = ROOT / "docs" / "manuscript" / "MANUSCRIPT.md"
TODO = ROOT / "docs" / "manuscript" / "OPEN_ITEMS.md"

NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")
YEAR = re.compile(r"20(1[6-9]|2[0-6])")


def _text() -> str:
    return MANUSCRIPT.read_text(encoding="utf-8")


def _body(text: str) -> str:
    """Prose from the abstract to the references, minus things that are not data."""
    body = text[text.index("## Abstract") : text.index("## References")]
    body = re.sub(r"\d{4}-\d{2}-\d{2}", "", body)  # ISO dates
    body = "\n".join(ln for ln in body.splitlines() if not ln.startswith("#"))
    body = re.sub(r"`[^`]*`", "", body)  # code spans (file names, commands)
    body = re.sub(r"\b(Section|Table|Appendix)s? [\w.]+", "", body)
    return body


def body_numbers(text: str) -> set[str]:
    """Every numeric token in the prose except calendar years 2016-2026."""
    toks = {t.rstrip(",") for t in NUMBER.findall(_body(text))}
    return {t for t in toks if not YEAR.fullmatch(t)}


def appendix_rows(text: str) -> list[dict[str, str]]:
    """Parse the Appendix A table into dicts."""
    section = text[text.index("## Appendix A") :]
    rows = []
    for ln in section.splitlines():
        if not ln.startswith("|") or ln.startswith("|---") or ln.startswith("| Number"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split(" | ")]
        assert len(cells) == 4, f"bad appendix row: {ln}"
        rows.append(dict(zip(("number", "source", "locator", "use"), cells)))
    return rows


def _norm(s: object) -> str:
    return str(s).strip()


def _eq(cell: object, want: str) -> bool:
    if _norm(cell) == want:
        return True
    try:
        return float(cell) == float(want)
    except (TypeError, ValueError):
        return False


def _filter(df: pd.DataFrame, clause: str) -> pd.DataFrame:
    for part in clause.split(", "):
        m = re.fullmatch(r"(\w+)(!=|<|=)(.*)", part.strip())
        assert m, f"bad where clause: {part}"
        col, op, val = m.groups()
        if op == "=":
            df = df[[_eq(c, val) for c in df[col]]]
        elif op == "!=":
            df = df[[not _eq(c, val) for c in df[col]]]
        else:
            df = df[pd.to_numeric(df[col]) < float(val)]
    return df


def _json_path(obj: object, path: str) -> float:
    for key in path.split("."):
        obj = obj[key]  # type: ignore[index]
    return float(obj)  # type: ignore[arg-type]


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def evaluate(row: dict[str, str]) -> bool:
    """Return True if the row's locator reproduces its number from its source."""
    num = row["number"]
    path = ROOT / row["source"]
    assert path.exists(), f"missing source {row['source']}"
    opts = [o.strip() for o in row["locator"].split("; ")]
    kv = {
        o.split("=", 1)[0]: o.split("=", 1)[1]
        for o in opts
        if "=" in o and not o.startswith("where ")
    }
    where = next((o[len("where ") :] for o in opts if o.startswith("where ")), None)
    if "grep" in kv:
        phrase = kv["grep"]
        return num in phrase and _squash(phrase) in _squash(path.read_text(encoding="utf-8"))
    if "path" in kv:
        value = _json_path(json.loads(path.read_text(encoding="utf-8")), kv["path"])
    else:
        df = pd.read_csv(path)
        if where:
            df = _filter(df, where)
        agg = kv.get("agg")
        col = kv["col"]
        if agg == "count":
            value = float(len(df))
        elif agg:
            value = float(getattr(pd.to_numeric(df[col]), agg)())
        else:
            assert len(df) == 1, f"{row['number']}: locator selects {len(df)} rows"
            value = float(df[col].iloc[0])
    for o in opts:
        if re.fullmatch(r"x[-\d.e]+", o):
            value *= float(o[1:])
        elif o == "abs":
            value = abs(value)
    dec = len(num.split(".")[1]) if "." in num else 0
    got = Decimal(repr(value)).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)
    return got == Decimal(num.replace(",", ""))


class TestManuscript(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _text()
        cls.rows = appendix_rows(cls.text)

    def test_header_states_unsubmitted_draft_and_author(self) -> None:
        head = self.text[: self.text.index("## Abstract")]
        self.assertIn("**Author:** Priyatham Chimmani", head)
        self.assertIn("UNSUBMITTED DRAFT", head)
        self.assertIn("has not been submitted", head)

    def test_imrad_sections_present(self) -> None:
        for h in (
            "## Abstract",
            "## 1. Introduction",
            "## 2. Data",
            "## 3. Methods",
            "## 4. Results",
            "## 5. Robustness",
            "## 6. Limitations",
            "## 7. Reproducibility statement",
            "## References",
            "## Appendix A",
        ):
            self.assertIn(h, self.text)

    def test_appendix_is_populated(self) -> None:
        self.assertGreater(len(self.rows), 100)

    def test_every_registered_number_reproduces_from_its_source(self) -> None:
        failures = [
            f"{r['number']} <- {r['source']} [{r['locator']}]" for r in self.rows if not evaluate(r)
        ]
        self.assertEqual(failures, [])

    def test_every_number_in_the_text_is_registered(self) -> None:
        registered = {r["number"] for r in self.rows}
        self.assertEqual(sorted(body_numbers(self.text) - registered), [])

    def test_every_registered_number_is_used_in_the_text(self) -> None:
        used = body_numbers(self.text)
        self.assertEqual(sorted({r["number"] for r in self.rows} - used), [])

    def test_appendix_rows_have_a_use_and_are_unique(self) -> None:
        keys = [(r["number"], r["source"], r["locator"]) for r in self.rows]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(r["use"] for r in self.rows))

    def test_references_are_limited_to_the_verified_repository(self) -> None:
        refs = self.text[self.text.index("## References") : self.text.index("## Appendix A")]
        urls = set(re.findall(r"https?://[^\s)`]+", refs))
        self.assertEqual(urls, {"https://github.com/priyatham9/ehs-osha-analysis"})
        self.assertNotRegex(refs.lower(), r"doi\.org|10\.\d{4,}/")

    def test_todo_lists_unverified_references(self) -> None:
        todo = TODO.read_text(encoding="utf-8")
        self.assertIn("unverified", todo.lower())


if __name__ == "__main__":
    unittest.main()
