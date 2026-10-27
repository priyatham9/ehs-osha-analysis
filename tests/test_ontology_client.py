"""Tests for the generated typed ontology client (src/ehs_osha/ontology/client.py)."""

from __future__ import annotations

import copy
import dataclasses
import subprocess
import sys
import typing
import unittest

import _context  # noqa: F401
from test_ontology import small_store

from ehs_osha.ontology import ActionRejected, OntologySpec, load_spec
from ehs_osha.ontology import client as C
from ehs_osha.ontology.codegen import generate, plural, snake

ROOT = _context.ROOT


class TestDrift(unittest.TestCase):
    def test_committed_client_matches_spec(self) -> None:
        committed = (ROOT / "src" / "ehs_osha" / "ontology" / "client.py").read_text(encoding="utf-8")
        self.assertEqual(committed, generate(), "run scripts/generate_ontology_client.py")

    def test_check_script_passes(self) -> None:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_ontology_client.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_spec_change_changes_output_and_still_compiles(self) -> None:
        raw = copy.deepcopy(load_spec().raw)
        for ot in raw["object_types"]:
            if ot["api_name"] == "Sector":
                ot["properties"].append({"api_name": "extra_note", "type": "string", "nullable": True,
                                         "description": "added in test"})
        changed = generate(OntologySpec(raw))
        self.assertNotEqual(changed, generate())
        self.assertIn("extra_note: Optional[str]", changed)
        compile(changed, "client.py", "exec")


class TestShape(unittest.TestCase):
    def test_every_type_property_link_and_action_is_generated(self) -> None:
        spec = load_spec()
        for name, ot in spec.object_types.items():
            cls = getattr(C, name)
            fields = {f.name for f in dataclasses.fields(cls)} - {"_store"}
            self.assertEqual(fields, {p["api_name"] for p in ot["properties"]})
            self.assertTrue(hasattr(C, f"{name}Set"))
            for link in spec.links_from(name):
                self.assertTrue(hasattr(cls, link), (name, link))
                self.assertTrue(hasattr(getattr(C, f"{name}Set"), link), (name, link))
            self.assertTrue(hasattr(C.OntologyClient, plural(snake(name))))
        for action in spec.action_types:
            self.assertTrue(hasattr(C.OntologyClient, action), action)

    def test_literal_matches_allowed_values(self) -> None:
        spec = load_spec()
        hints = typing.get_type_hints(C.OntologyClient.flag_filing_implausible, vars(C))
        allowed = {p["api_name"]: p["allowed_values"] for p in spec.action_types["flag_filing_implausible"]["parameters"]
                   if "allowed_values" in p}
        self.assertEqual(set(typing.get_args(hints["reason"])), set(allowed["reason"]))

    def test_property_types(self) -> None:
        hints = typing.get_type_hints(C.Filing, vars(C))
        self.assertIs(hints["year_filing_for"], int)
        self.assertEqual(hints["total_hours_worked"], typing.Optional[float])
        self.assertIs(hints["analyst_flag"], bool)


class TestBehaviour(unittest.TestCase):
    def setUp(self) -> None:
        self.store = small_store()
        self.client = C.OntologyClient(self.store)

    def test_objects_match_store(self) -> None:
        self.assertEqual(len(self.client.filings), self.store.objects("Filing").count())
        f = next(iter(self.client.filings))
        self.assertIsInstance(f, C.Filing)
        self.assertEqual(f.filing_id, self.store.get("Filing", f.filing_id).primary_key)
        self.assertEqual(self.client.get_filing(f.filing_id), f)

    def test_where_and_links_match_untyped_runtime(self) -> None:
        bad = self.client.filings.where(screen_implausible=True)
        self.assertEqual(bad.primary_keys(), self.store.objects("Filing").where(screen_implausible=True).primary_keys())
        f = next(iter(self.client.filings))
        est = f.establishment().one()
        self.assertIsInstance(est, C.Establishment)
        self.assertEqual(est.establishment_id, f.establishment_id)
        self.assertGreaterEqual(len(est.filings()), 1)
        around = self.client.filings.establishment()
        self.assertIsInstance(around, C.EstablishmentSet)
        self.assertEqual(
            around.primary_keys(), self.store.objects("Filing").search_around("establishment").primary_keys()
        )
        with self.assertRaises(TypeError):
            self.client.filings.where(not_a_property=1)  # type: ignore[call-arg]

    def test_action_through_typed_method_and_rejection(self) -> None:
        good = next(iter(self.client.filings.where(screen_implausible=False)))
        entry = self.client.flag_filing_implausible(good, "employee_count_mistyped", actor="analyst@example.org")
        self.assertEqual(entry.action_type, "flag_filing_implausible")
        self.assertTrue(self.client.get_filing(good.filing_id).analyst_flag)
        with self.assertRaises(ActionRejected):
            self.client.flag_filing_implausible(good.filing_id, "employee_count_mistyped", actor="a")
        self.client.clear_analyst_flag(good, "hours confirmed by site", actor="analyst@example.org")
        self.assertFalse(self.client.get_filing(good.filing_id).analyst_flag)


if __name__ == "__main__":
    unittest.main()
