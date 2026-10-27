"""The committed docs/ontology_explorer.html must match its generator."""

from __future__ import annotations

import importlib.util
import json
import re
import unittest

import _context  # noqa: F401
from _context import ROOT

SCRIPT = ROOT / "scripts" / "build_ontology_explorer.py"
PAGE = ROOT / "docs" / "ontology_explorer.html"


def _load():
    spec = importlib.util.spec_from_file_location("build_ontology_explorer", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OntologyExplorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()
        cls.rendered = cls.mod.render()
        cls.committed = PAGE.read_text(encoding="utf-8")

    def test_page_is_current(self):
        self.assertEqual(
            self.committed, self.rendered,
            "docs/ontology_explorer.html is stale; run python scripts/build_ontology_explorer.py",
        )

    def test_deterministic(self):
        self.assertEqual(self.rendered, self.mod.render())

    def test_no_em_dash_or_external_resources(self):
        self.assertNotIn("—", self.committed)
        self.assertIsNone(re.search(r"(src|href)=[\"']https?://", self.committed))
        self.assertNotIn("<link", self.committed)

    def test_embedded_json_parses(self):
        m = re.search(r'<script id="data" type="application/json">(.*?)</script>', self.committed, re.S)
        self.assertIsNotNone(m)
        data = json.loads(m.group(1))
        self.assertEqual(len(data["object_types"]), 7)
        self.assertEqual(len(data["link_types"]), 7)
        self.assertEqual(len(data["action_types"]), 4)
        self.assertEqual(len(data["functions"]), 5)
        for name in ("ReportingYear", "Sector", "Industry", "PeerGroup", "QualityFlag"):
            t = data["tables"][name]
            self.assertTrue(t["rows"])
            for row in t["rows"]:
                self.assertEqual(len(row), len(t["cols"]))
        self.assertNotIn("Establishment", data["tables"])
        self.assertNotIn("Filing", data["tables"])


if __name__ == "__main__":
    unittest.main()
