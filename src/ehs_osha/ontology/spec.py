"""Load and validate the declarative ontology spec (``spec.json``).

The spec is plain JSON so it needs no new dependency. Validation is static:
it checks the spec against itself (keys exist, links resolve, actions edit only
editable properties, functions point at code that exists) before any data is
read. Data-level checks (primary-key uniqueness, property types, dangling
foreign keys) happen when objects are loaded, in :mod:`.runtime`.

All errors are collected and raised together, so one run lists every problem.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

SPEC_PATH = Path(__file__).with_name("spec.json")

PROPERTY_TYPES = ("string", "integer", "double", "boolean", "timestamp")
CARDINALITIES = ("many_to_one", "many_to_many")
JOIN_RULES = ("source_boolean_property_named_by_target_key",)
OPERATORS = ("equals", "not_equals", "is_null", "not_null")
PARAMETER_TYPES = PROPERTY_TYPES + ("object_reference",)


class SpecError(ValueError):
    """Raised when the ontology spec is internally inconsistent."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = list(errors)
        super().__init__("invalid ontology spec:\n  - " + "\n  - ".join(self.errors))


def _resolve_dotted(path: str) -> Any:
    """Import ``package.module.attr`` and return ``attr``.

    Raises:
        ImportError / AttributeError: If the path does not resolve.
    """
    module_name, _, attr = path.rpartition(".")
    if not module_name:
        raise ImportError(f"{path!r} is not a dotted path")
    return getattr(importlib.import_module(module_name), attr)


def _check_value_type(value: Any, type_name: str) -> bool:
    """Return True if a JSON literal is compatible with a property type."""
    if value is None:
        return True
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "double":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


class OntologySpec:
    """A validated ontology spec with lookup helpers.

    Attributes:
        raw: The spec as loaded (deep-copied).
        object_types: api_name -> object type dict.
        link_types: api_name -> link type dict.
        action_types: api_name -> action type dict.
        functions: api_name -> function dict.
    """

    def __init__(self, raw: Dict[str, Any]) -> None:
        self.raw = copy.deepcopy(raw)
        self.object_types = {o["api_name"]: o for o in self.raw.get("object_types", [])}
        self.link_types = {lk["api_name"]: lk for lk in self.raw.get("link_types", [])}
        self.action_types = {a["api_name"]: a for a in self.raw.get("action_types", [])}
        self.functions = {f["api_name"]: f for f in self.raw.get("functions", [])}

    def properties(self, object_type: str) -> Dict[str, Dict[str, Any]]:
        """Return property api_name -> property dict for an object type."""
        return {p["api_name"]: p for p in self.object_types[object_type]["properties"]}

    def links_from(self, object_type: str) -> Dict[str, Dict[str, Any]]:
        """Return link name -> traversal descriptor for links leaving a type.

        Each descriptor has ``link`` (the link type dict), ``direction``
        (``"forward"`` from source to target or ``"reverse"``) and ``to``
        (the object type reached).
        """
        out: Dict[str, Dict[str, Any]] = {}
        for lk in self.link_types.values():
            if lk["source"] == object_type:
                out[lk["source_link_name"]] = {"link": lk, "direction": "forward", "to": lk["target"]}
            if lk["target"] == object_type:
                out[lk["target_link_name"]] = {"link": lk, "direction": "reverse", "to": lk["source"]}
        return out

    def to_json(self) -> Dict[str, Any]:
        """Return a deep copy of the raw spec."""
        return copy.deepcopy(self.raw)


def validate(raw: Dict[str, Any]) -> List[str]:
    """Return every consistency problem in a raw spec dict (empty if valid)."""
    errors: List[str] = []
    for key in ("ontology", "object_types", "link_types", "action_types", "functions"):
        if key not in raw:
            errors.append(f"missing top-level key {key!r}")
    if errors:
        return errors

    props: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for ot in raw["object_types"]:
        name = ot.get("api_name", "<unnamed>")
        if name in props:
            errors.append(f"object type {name!r} defined twice")
        plist = ot.get("properties", [])
        pmap = {p.get("api_name"): p for p in plist}
        if len(pmap) != len(plist):
            errors.append(f"{name}: duplicate property api_name")
        props[name] = pmap
        for p in plist:
            if p.get("type") not in PROPERTY_TYPES:
                errors.append(f"{name}.{p.get('api_name')}: unknown type {p.get('type')!r}")
            if "default" in p and not _check_value_type(p["default"], p.get("type", "")):
                errors.append(f"{name}.{p['api_name']}: default does not match type")
        pk = ot.get("primary_key")
        if pk not in pmap:
            errors.append(f"{name}: primary key {pk!r} is not a property")
        elif pmap[pk].get("nullable", True):
            errors.append(f"{name}: primary key {pk!r} must be non-nullable")
        elif pmap[pk].get("editable"):
            errors.append(f"{name}: primary key {pk!r} must not be editable")
        if ot.get("title_property") not in pmap:
            errors.append(f"{name}: title property {ot.get('title_property')!r} is not a property")

    link_names: Dict[str, set] = {name: set() for name in props}
    for lk in raw["link_types"]:
        name = lk.get("api_name", "<unnamed>")
        src, tgt = lk.get("source"), lk.get("target")
        if src not in props or tgt not in props:
            errors.append(f"link {name}: endpoint {src!r} -> {tgt!r} is not an object type")
            continue
        card = lk.get("cardinality")
        if card not in CARDINALITIES:
            errors.append(f"link {name}: unknown cardinality {card!r}")
        if card == "many_to_one":
            fk = lk.get("foreign_key")
            if fk not in props[src]:
                errors.append(f"link {name}: foreign key {fk!r} is not a property of {src}")
            else:
                tpk = next(o["primary_key"] for o in raw["object_types"] if o["api_name"] == tgt)
                ftype = props[src][fk].get("type")
                ptype = props[tgt].get(tpk, {}).get("type")
                if ftype != ptype:
                    errors.append(
                        f"link {name}: foreign key type {ftype!r} does not match "
                        f"{tgt}.{tpk} type {ptype!r}"
                    )
                if props[src][fk].get("editable"):
                    errors.append(f"link {name}: foreign key {fk!r} must not be editable")
        if card == "many_to_many" and lk.get("join_rule") not in JOIN_RULES:
            errors.append(f"link {name}: unknown join_rule {lk.get('join_rule')!r}")
        for side, ot in (("source_link_name", src), ("target_link_name", tgt)):
            ln = lk.get(side)
            if not ln:
                errors.append(f"link {name}: missing {side}")
            elif ln in link_names[ot] or ln in props[ot]:
                errors.append(f"link {name}: link name {ln!r} clashes on {ot}")
            else:
                link_names[ot].add(ln)

    for act in raw["action_types"]:
        name = act.get("api_name", "<unnamed>")
        params = {p.get("api_name"): p for p in act.get("parameters", [])}
        for p in params.values():
            if p.get("type") not in PARAMETER_TYPES:
                errors.append(f"action {name}: parameter {p.get('api_name')!r} has unknown type")
            if p.get("type") == "object_reference" and p.get("object_type") not in props:
                errors.append(f"action {name}: parameter {p['api_name']!r} references unknown type")
            rw = p.get("required_when")
            if rw and rw.get("parameter") not in params:
                errors.append(f"action {name}: required_when refers to unknown parameter")
        for crit in act.get("submission_criteria", []):
            par = params.get(crit.get("parameter"))
            if not par or par.get("type") != "object_reference":
                errors.append(f"action {name}: criterion must name an object parameter")
                continue
            ot = par["object_type"]
            prop = props[ot].get(crit.get("property"))
            if prop is None:
                errors.append(f"action {name}: criterion property {crit.get('property')!r} not on {ot}")
            elif crit.get("operator") not in OPERATORS:
                errors.append(f"action {name}: unknown operator {crit.get('operator')!r}")
            elif not _check_value_type(crit.get("value"), prop["type"]):
                errors.append(f"action {name}: criterion value does not match {ot}.{prop['api_name']}")
            if not crit.get("failure_message"):
                errors.append(f"action {name}: criterion needs a failure_message")
        for edit in act.get("edits", []):
            par = params.get(edit.get("object_parameter"))
            if not par or par.get("type") != "object_reference":
                errors.append(f"action {name}: edit must target an object parameter")
                continue
            ot = par["object_type"]
            for prop_name, value in edit.get("set", {}).items():
                prop = props[ot].get(prop_name)
                if prop is None:
                    errors.append(f"action {name}: edits unknown property {ot}.{prop_name}")
                    continue
                if not prop.get("editable"):
                    errors.append(f"action {name}: {ot}.{prop_name} is not editable")
                if isinstance(value, str) and value.startswith("$"):
                    if value[1:] not in params:
                        errors.append(f"action {name}: {value} is not a parameter")
                elif not _check_value_type(value, prop["type"]):
                    errors.append(f"action {name}: literal for {ot}.{prop_name} has wrong type")
                elif value is None and not prop.get("nullable", True):
                    errors.append(f"action {name}: {ot}.{prop_name} is not nullable")

    for fn in raw["functions"]:
        name = fn.get("api_name", "<unnamed>")
        target = fn.get("reuses")
        if not target:
            errors.append(f"function {name}: no 'reuses' reference")
            continue
        try:
            _resolve_dotted(target)
        except (ImportError, AttributeError):
            errors.append(f"function {name}: {target!r} does not resolve to existing code")
    return errors


def load_spec(source: Optional[Union[Path, str, Dict[str, Any]]] = None) -> OntologySpec:
    """Load and validate a spec.

    Args:
        source: A path to a JSON spec, an already-parsed dict, or ``None`` for
            the bundled ``spec.json``.

    Returns:
        A validated :class:`OntologySpec`.

    Raises:
        SpecError: Listing every problem found.
    """
    if source is None:
        source = SPEC_PATH
    raw = source if isinstance(source, dict) else json.loads(Path(source).read_text(encoding="utf-8"))
    errors = validate(raw)
    if errors:
        raise SpecError(errors)
    return OntologySpec(raw)
