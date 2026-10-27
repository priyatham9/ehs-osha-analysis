"""In-memory object store: objects, link traversal, object sets and actions.

This is the small runtime behind the spec. It plays the part of Foundry's
object storage plus the Actions service:

* objects are typed, keyed and checked against the spec when loaded;
* links are resolved from foreign-key properties (or a join rule) and can be
  traversed in either direction, from one object or a whole object set;
* the only way to change an object after loading is :meth:`ObjectStore.apply`,
  which validates parameters and submission criteria, edits only properties
  the spec marks editable, and appends an entry (who, when, why, before and
  after) to an append-only action log.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional

import pandas as pd

from .spec import OntologySpec, load_spec


class ObjectValidationError(ValueError):
    """Raised when loaded data does not fit its object type."""


class ActionRejected(ValueError):
    """Raised when an action fails parameter validation or submission criteria.

    Attributes:
        errors: Every reason the submission was refused.
    """

    def __init__(self, action: str, errors: List[str]) -> None:
        self.errors = list(errors)
        super().__init__(f"{action} rejected: " + "; ".join(self.errors))


@dataclass(frozen=True)
class OntologyObject:
    """A read-only view of one object.

    Attributes:
        object_type: The object type api_name.
        primary_key: The primary-key value.
        title: The value of the title property.
        properties: Read-only mapping of property values.
    """

    object_type: str
    primary_key: Any
    title: Any
    properties: Mapping[str, Any]

    def __getitem__(self, name: str) -> Any:
        return self.properties[name]


@dataclass
class ActionLogEntry:
    """One applied action, as recorded in the action log."""

    action_id: str
    action_type: str
    actor: str
    timestamp: str
    parameters: Dict[str, Any]
    edits: List[Dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "parameters": copy.deepcopy(self.parameters),
            "edits": copy.deepcopy(self.edits),
        }


def _is_missing(value: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    return isinstance(value, float) and math.isnan(value)


def coerce_value(value: Any, type_name: str) -> Any:
    """Convert a pandas/numpy scalar to the Python type a property declares.

    Raises:
        ObjectValidationError: If the value cannot represent that type.
    """
    if _is_missing(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if type_name == "string":
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)
    if type_name == "boolean":
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        raise ObjectValidationError(f"{value!r} is not a boolean")
    if type_name == "integer":
        if isinstance(value, bool):
            raise ObjectValidationError(f"{value!r} is not an integer")
        if isinstance(value, float):
            if not value.is_integer():
                raise ObjectValidationError(f"{value!r} is not an integer")
            return int(value)
        if isinstance(value, int):
            return value
        raise ObjectValidationError(f"{value!r} is not an integer")
    if type_name == "double":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ObjectValidationError(f"{value!r} is not a number")
        return float(value)
    if type_name == "timestamp":
        return str(value)
    raise ObjectValidationError(f"unknown type {type_name!r}")


class ObjectSet:
    """An ordered, immutable set of objects of one type (Foundry Object Set)."""

    def __init__(self, store: "ObjectStore", object_type: str, keys: Iterable[Any]) -> None:
        self._store = store
        self.object_type = object_type
        self._keys = list(dict.fromkeys(keys))

    def __iter__(self) -> Iterator[OntologyObject]:
        for k in self._keys:
            yield self._store.get(self.object_type, k)

    def __len__(self) -> int:
        return len(self._keys)

    def count(self) -> int:
        """Number of objects in the set."""
        return len(self._keys)

    def primary_keys(self) -> List[Any]:
        """Primary keys, in set order."""
        return list(self._keys)

    def where(self, **equals: Any) -> "ObjectSet":
        """Filter to objects whose properties equal every given value."""
        props = self._store.spec.properties(self.object_type)
        for name in equals:
            if name not in props:
                raise KeyError(f"{self.object_type} has no property {name!r}")
        rows = self._store._rows[self.object_type]
        keep = [k for k in self._keys if all(rows[k][n] == v for n, v in equals.items())]
        return ObjectSet(self._store, self.object_type, keep)

    def filter(self, predicate: Callable[[OntologyObject], bool]) -> "ObjectSet":
        """Filter with an arbitrary predicate on each object."""
        return ObjectSet(self._store, self.object_type, [o.primary_key for o in self if predicate(o)])

    def search_around(self, link_name: str) -> "ObjectSet":
        """Follow a link from every object in the set (Foundry Search Around)."""
        hop = self._store._hop(self.object_type, link_name)
        keys: List[Any] = []
        for k in self._keys:
            keys.extend(self._store._traverse_keys(self.object_type, k, link_name))
        return ObjectSet(self._store, hop["to"], keys)

    def one(self) -> Optional[OntologyObject]:
        """The single object in the set, ``None`` if empty.

        Raises:
            ValueError: If the set holds more than one object.
        """
        if len(self._keys) > 1:
            raise ValueError(f"expected at most one {self.object_type}, got {len(self._keys)}")
        return self._store.get(self.object_type, self._keys[0]) if self._keys else None

    def to_frame(self) -> pd.DataFrame:
        """Return the set's properties as a DataFrame (one row per object)."""
        rows = self._store._rows[self.object_type]
        cols = list(self._store.spec.properties(self.object_type))
        return pd.DataFrame([rows[k] for k in self._keys], columns=cols)


class ObjectStore:
    """Typed objects for every type in a spec, with links and actions.

    Args:
        spec: A validated spec; defaults to the bundled one.
        clock: Zero-argument callable returning an aware ``datetime``; injected
            so tests can pin action timestamps.
    """

    def __init__(
        self,
        spec: Optional[OntologySpec] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.spec = spec or load_spec()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._rows: Dict[str, Dict[Any, Dict[str, Any]]] = {t: {} for t in self.spec.object_types}
        self._reverse_index: Dict[str, Dict[Any, List[Any]]] = {}
        self.action_log: List[ActionLogEntry] = []

    # ------------------------------------------------------------------ load
    def add_objects(self, object_type: str, records: Iterable[Mapping[str, Any]]) -> int:
        """Validate and add objects of one type.

        Missing editable properties take their spec default. Unknown keys are
        ignored, so a wide pipeline frame can be passed directly.

        Returns:
            Number of objects added.

        Raises:
            ObjectValidationError: On a type mismatch, a null in a non-nullable
                property, or a duplicate primary key.
        """
        ot = self.spec.object_types[object_type]
        props = self.spec.properties(object_type)
        pk_name = ot["primary_key"]
        table = self._rows[object_type]
        added = 0
        for rec in records:
            row: Dict[str, Any] = {}
            for name, prop in props.items():
                raw = rec.get(name, prop.get("default"))
                try:
                    value = coerce_value(raw, prop["type"])
                except ObjectValidationError as exc:
                    raise ObjectValidationError(f"{object_type}.{name}: {exc}") from None
                if value is None and not prop.get("nullable", True):
                    raise ObjectValidationError(
                        f"{object_type}.{name} is not nullable (primary key "
                        f"{rec.get(pk_name)!r})"
                    )
                row[name] = value
            pk = row[pk_name]
            if pk in table:
                raise ObjectValidationError(f"duplicate {object_type} primary key {pk!r}")
            table[pk] = row
            added += 1
        self._reverse_index.clear()
        return added

    # ----------------------------------------------------------------- read
    def get(self, object_type: str, primary_key: Any) -> OntologyObject:
        """Return one object.

        Raises:
            KeyError: If no such object exists.
        """
        row = self._rows[object_type][primary_key]
        title = row[self.spec.object_types[object_type]["title_property"]]
        return OntologyObject(object_type, primary_key, title, MappingProxyType(dict(row)))

    def objects(self, object_type: str) -> ObjectSet:
        """All objects of a type, as an object set."""
        return ObjectSet(self, object_type, self._rows[object_type].keys())

    def linked(self, obj: OntologyObject, link_name: str) -> ObjectSet:
        """Objects reached from ``obj`` along ``link_name``."""
        hop = self._hop(obj.object_type, link_name)
        return ObjectSet(self, hop["to"], self._traverse_keys(obj.object_type, obj.primary_key, link_name))

    def _hop(self, object_type: str, link_name: str) -> Dict[str, Any]:
        hops = self.spec.links_from(object_type)
        if link_name not in hops:
            raise KeyError(f"{object_type} has no link {link_name!r}; has {sorted(hops)}")
        return hops[link_name]

    def _traverse_keys(self, object_type: str, key: Any, link_name: str) -> List[Any]:
        hop = self._hop(object_type, link_name)
        lk = hop["link"]
        row = self._rows[object_type][key]
        if lk["cardinality"] == "many_to_one":
            if hop["direction"] == "forward":
                fk = row[lk["foreign_key"]]
                return [fk] if fk in self._rows[lk["target"]] else []
            return self._reverse(lk).get(key, [])
        # many_to_many via join rule: the source carries a boolean property
        # named by each target's primary key.
        if hop["direction"] == "forward":
            return [t for t in self._rows[lk["target"]] if row.get(t) is True]
        return [s for s, srow in self._rows[lk["source"]].items() if srow.get(key) is True]

    def _reverse(self, lk: Dict[str, Any]) -> Dict[Any, List[Any]]:
        idx = self._reverse_index.get(lk["api_name"])
        if idx is None:
            idx = {}
            for skey, srow in self._rows[lk["source"]].items():
                idx.setdefault(srow[lk["foreign_key"]], []).append(skey)
            self._reverse_index[lk["api_name"]] = idx
        return idx

    def link_pairs(self, link_api_name: str) -> List[tuple]:
        """All resolved (source_pk, target_pk) pairs of a link type."""
        lk = self.spec.link_types[link_api_name]
        name = lk["source_link_name"]
        return [(s, t) for s in self._rows[lk["source"]] for t in self._traverse_keys(lk["source"], s, name)]

    def integrity_report(self) -> Dict[str, Dict[str, int]]:
        """Per many-to-one link: resolved, null and dangling foreign keys.

        A dangling key is a non-null foreign key with no target object, as
        when a filing's NAICS code is not among the committed peer cells.
        """
        report: Dict[str, Dict[str, int]] = {}
        for name, lk in self.spec.link_types.items():
            if lk["cardinality"] != "many_to_one":
                continue
            targets = self._rows[lk["target"]]
            counts = {"resolved": 0, "null": 0, "dangling": 0}
            for row in self._rows[lk["source"]].values():
                fk = row[lk["foreign_key"]]
                counts["null" if fk is None else "resolved" if fk in targets else "dangling"] += 1
            report[name] = counts
        return report

    # -------------------------------------------------------------- actions
    def apply(self, action_type: str, parameters: Mapping[str, Any], actor: str) -> ActionLogEntry:
        """Validate and apply an action, then log it.

        Args:
            action_type: Action api_name.
            parameters: Parameter values; object references are passed as the
                target object's primary key (or an :class:`OntologyObject`).
            actor: Who is submitting. Required, as in a Foundry action log.

        Returns:
            The appended :class:`ActionLogEntry`.

        Raises:
            ActionRejected: With every reason, if anything fails. Nothing is
                edited and nothing is logged in that case.
            KeyError: If the action type does not exist.
        """
        act = self.spec.action_types[action_type]
        params = {p["api_name"]: p for p in act["parameters"]}
        errors: List[str] = []
        if not isinstance(actor, str) or not actor.strip():
            errors.append("actor is required")
        unknown = set(parameters) - set(params)
        if unknown:
            errors.append(f"unknown parameters {sorted(unknown)}")

        values: Dict[str, Any] = {}
        targets: Dict[str, Any] = {}
        for name, p in params.items():
            v = parameters.get(name)
            if isinstance(v, OntologyObject):
                v = v.primary_key
            if isinstance(v, str) and not v.strip() and p["type"] == "string":
                v = None
            values[name] = v
            rw = p.get("required_when")
            required = p.get("required") or (rw and parameters.get(rw["parameter"]) == rw["equals"])
            if v is None:
                if required:
                    errors.append(f"{name} is required")
                continue
            if p["type"] == "object_reference":
                if v not in self._rows[p["object_type"]]:
                    errors.append(f"{name}: no {p['object_type']} with key {v!r}")
                else:
                    targets[name] = v
                continue
            if p["type"] == "string" and not isinstance(v, str):
                errors.append(f"{name} must be a string")
                continue
            if "allowed_values" in p and v not in p["allowed_values"]:
                errors.append(f"{name} must be one of {p['allowed_values']}")
            if isinstance(v, str):
                if len(v.strip()) < p.get("min_length", 0):
                    errors.append(f"{name} must be at least {p['min_length']} characters")
                if "max_length" in p and len(v) > p["max_length"]:
                    errors.append(f"{name} must be at most {p['max_length']} characters")

        if not errors:
            for crit in act.get("submission_criteria", []):
                ot = params[crit["parameter"]]["object_type"]
                current = self._rows[ot][targets[crit["parameter"]]][crit["property"]]
                op = crit["operator"]
                ok = {
                    "equals": current == crit.get("value"),
                    "not_equals": current != crit.get("value"),
                    "is_null": current is None,
                    "not_null": current is not None,
                }[op]
                if not ok:
                    errors.append(crit["failure_message"])
        if errors:
            raise ActionRejected(action_type, errors)

        edits: List[Dict[str, Any]] = []
        for edit in act.get("edits", []):
            pname = edit["object_parameter"]
            ot = params[pname]["object_type"]
            row = self._rows[ot][targets[pname]]
            for prop, spec_value in edit["set"].items():
                new = values[spec_value[1:]] if isinstance(spec_value, str) and spec_value.startswith("$") else spec_value
                edits.append({"object_type": ot, "primary_key": targets[pname], "property": prop, "before": row[prop], "after": new})
                row[prop] = new

        entry = ActionLogEntry(
            action_id=f"act-{len(self.action_log) + 1:06d}",
            action_type=action_type,
            actor=actor,
            timestamp=self.clock().astimezone(timezone.utc).isoformat(),
            parameters=dict(values),
            edits=edits,
        )
        self.action_log.append(entry)
        return entry

    def edit_history(self, object_type: str, primary_key: Any) -> List[Dict[str, Any]]:
        """Every logged edit to one object, oldest first, with who and when."""
        out = []
        for entry in self.action_log:
            for e in entry.edits:
                if e["object_type"] == object_type and e["primary_key"] == primary_key:
                    out.append({"action_id": entry.action_id, "action_type": entry.action_type, "actor": entry.actor, "timestamp": entry.timestamp, **e})
        return out
