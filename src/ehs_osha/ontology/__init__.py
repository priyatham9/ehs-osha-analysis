"""Foundry-style ontology over the public OSHA ITA data.

An independent design in the style of a Palantir Foundry Ontology, built on
public data only. It is not affiliated with Palantir and uses no employer data.

``spec.json``     declarative object types, link types, action types, functions
``spec``          load and validate the spec
``runtime``       object store, object sets, link traversal, actions, action log
``functions``     ontology functions, adapters over the pipeline's metric code
``materialise``   build a store from the fixture/raw frame and committed tables
``export``        write a store to SQLite and JSON

See ``docs/ontology.md``. Run ``python3 -m ehs_osha.ontology --out DIR``.
"""

from __future__ import annotations

from .runtime import ActionRejected, ObjectSet, ObjectStore, OntologyObject
from .spec import OntologySpec, SpecError, load_spec

__all__ = [
    "ActionRejected",
    "ObjectSet",
    "ObjectStore",
    "OntologyObject",
    "OntologySpec",
    "SpecError",
    "load_spec",
]
