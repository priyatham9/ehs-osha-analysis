# A Foundry-style ontology for OSHA ITA filings

This is an independent design in the style of a Palantir Foundry Ontology. It
is built only on public OSHA data and this repository's own outputs. It is not
affiliated with or endorsed by Palantir, it does not need a Foundry account,
and it uses no employer data.

Code: `src/ehs_osha/ontology/`. Spec: `src/ehs_osha/ontology/spec.json`.
Tests: `tests/test_ontology.py`.

## Why an ontology on top of a pipeline

The pipeline answers one question: how much do implausible filings bias the
aggregate injury rate? An EHS team using these data needs more than a table.
They need to open a site, see its filings across years, see which screen rule
fired and how much of the national denominator that rule controls, compare the
site with the right peers, and record a judgement ("this form is wrong", "this
site is not comparable") so that the judgement changes the numbers and leaves
an audit trail. In Foundry those needs map to object types, links, functions
and actions. This package builds the same structure in plain Python so it runs
anywhere and can be checked by tests.

## Foundry concept to this build

| Foundry concept | This build |
|---|---|
| Ontology (object and link type definitions) | `spec.json`, loaded and checked by `spec.load_spec()`. Checks: primary and title keys exist, primary keys are non-nullable and not editable, property types are known, links point at real types, foreign-key types match the target key, link names do not clash, actions edit only editable properties and only reference real parameters, and each function's `reuses` path imports. Every error is reported at once. |
| Object Type (primary key, title, typed properties) | `object_types` in the spec. `ObjectStore.add_objects()` coerces each value to its declared type and rejects nulls in non-nullable properties and duplicate primary keys. |
| Backing datasets | `materialise.build_store()`. Establishment and Filing come from a harmonised frame (the synthetic fixture by default, or the real ITA files via `--data-dir`). ReportingYear, Sector, Industry, PeerGroup and QualityFlag come from the committed `outputs/tables/*.csv`. Every object has a `source` property. |
| Link Type (cardinality, foreign key or join) | `link_types`. Many-to-one links use a foreign-key property. The one many-to-many link (Filing to QualityFlag) is backed by the boolean flag columns. Links can be followed in both directions. `integrity_report()` counts resolved, null and dangling keys for each link. |
| Object Set, filters, Search Around | `ObjectSet.where()`, `.filter()`, `.search_around(link)` and `ObjectStore.linked(obj, link)`. |
| Function (on objects or object sets) | `functions.py`. Each function is a thin adapter that calls the pipeline module named in the spec under `reuses`. No rate or screen is written a second time. |
| Action Type (parameters, constraints, submission criteria, edits) | `action_types`. Parameters can declare `required`, `required_when`, `allowed_values`, `min_length` and `max_length`. Submission criteria are checks on the target object's current state, each with a failure message. Edits set editable properties, either to literals or to `$parameter` values. |
| Writeback | The editable Filing properties (`analyst_flag*`, `benchmark_excl*`). `ObjectStore.apply()` is the only way to change them. |
| Action log / edit history | Each applied action appends an `ActionLogEntry` with id, action type, actor, UTC timestamp, parameters, and the before and after value of every edit. `edit_history(type, pk)` returns one object's history. A rejected action changes nothing and writes nothing to the log. |
| Export / downstream datasets | `export.export_sqlite()` writes one table per object type with typed columns and an enforced primary key, a table for the many-to-many link, `action_log`, and `ontology_spec`. `export.export_json()` writes the same content as strict JSON (no NaN). |

## Object types and the decisions they support

| Object type | Key | Backing data | Decision it supports |
|---|---|---|---|
| Establishment | `establishment_id` | harmonised frame (latest filing) | The unit an EHS manager is accountable for and the unit OSHA inspects. `company_name` lets a corporate team group its sites. |
| Filing | `establishment_id-year` | harmonised frame after `quality.apply_screen` and `peers.add_peer_keys` | Should this form count? It holds the case counts (300A columns G-L), the exposure denominator, the six screen flags, the screen verdict (read-only), and the analyst writeback. |
| ReportingYear | `year` | `quality_by_year.csv` + `metrics_by_year.csv` | How far does this year's headline rate depend on its worst filings? In 2019, flagged filings held 99.6% of reported hours, and screening moved the aggregate TRIR from 0.016 to 4.018. |
| Sector | NAICS 2-digit | `quality_by_naics2.csv` | How exposed is the parent sector to implausible hours? |
| Industry | NAICS 3-digit | codes in `peer_percentiles_pooled.csv` (209) | The industry level used for peer groups. It is named only by the official NAICS 2022 title (`ehs_osha.naics`). Codes that are not 2022 subsectors keep the bare code and `has_official_title = false`. |
| PeerGroup | `naics3\|size_band` | `peer_percentiles_pooled.csv` (905 cells, 647 publishable) | Which peers should a site be compared with? Size bands come from employee counts, not OSHA's `size` code, which changed meaning in 2023. Cells below the minimum size are kept but marked not publishable. |
| QualityFlag | flag column | `quality.FLAG_COLUMNS` + `quality_flag_prevalence.csv` | Which rule fired on this form, and how much does that rule matter? `hours per employee > 4,500` covers 96.65% of all reported hours pooled across years. The contradiction flag is carried with `counts_in_verdict = false`. |

## Actions

| Action | Parameters | Submission criteria | Effect |
|---|---|---|---|
| `flag_filing_implausible` | filing, reason (enum), note (required if reason is `other`, max 500 characters) | the screen has not already excluded the filing; the filing is not already flagged | `analyst_flag = true` plus reason and note |
| `clear_analyst_flag` | filing, note (10-500 characters, required) | the filing is flagged | clears the flag and records the note |
| `exclude_from_benchmark` | filing, reason (enum), note (required if reason is `other`) | the screen has not already excluded the filing; the filing is not already excluded | `benchmark_excluded = true` |
| `restore_to_benchmark` | filing, note (10-500 characters, required) | the filing is excluded | `benchmark_excluded = false` |

The screen verdict cannot be edited by any action. Changing which filings fail
the screen means changing the screen's bounds, and the `plausibility_screen`
function shows what-if bounds without editing any object. Analyst flags and
benchmark exclusions are recorded separately from the screen. Both take a
filing out of the aggregates.

## Functions

| Function | Input | Reuses | Note |
|---|---|---|---|
| `plausibility_screen` | ObjectSet<Filing>, optional bounds | `quality.apply_screen` | What-if screen. Returns a verdict per filing and edits nothing. |
| `filing_rates` | Filing | `load.derive_fields` | Re-derives establishment TRIR and DART from the stored counts. |
| `aggregate_trir` | ObjectSet<Filing> | `quality.aggregate_trir` | Ratio of sums over included filings. |
| `aggregate_rates` | ObjectSet<Filing> | `metrics.compute_rates` | TRIR, DART, LTIR and severity, screened and unscreened. |
| `peer_position` | Filing | `peers.DEFAULT_PERCENTILES` | Reports the percentile band of the peer group that the filing's TRIR falls in. Returns a status instead of a band when the filing is excluded, has no rate, or sits in a non-publishable cell. |

"Included" means the filing passes the screen and has neither an analyst flag
nor a benchmark exclusion. With no actions applied, `aggregate_rates` on the
fixture equals `metrics.compute_rates` on the screened fixture frame, both
pooled and for each year. The tests assert this. They also assert that after a
flag, the aggregate equals the pipeline's own computation with that filing
removed.

## Running it

```bash
PYTHONPATH=src python3 -m ehs_osha.ontology --out /tmp/ontology            # synthetic fixture
PYTHONPATH=src python3 -m ehs_osha.ontology --out /tmp/ontology --data-dir data/raw   # real ITA files
cd tests && python3 -m unittest test_ontology
```

The command prints how many objects of each type it built and the link
integrity report, then writes `ontology.sqlite` and `ontology.json` to
`--out`. It never writes under `outputs/`. From Python:

```python
from ehs_osha.ontology.materialise import build_store
from ehs_osha.ontology import functions as F

store = build_store()
site = next(iter(store.objects("Establishment")))
filings = store.linked(site, "filings")
F.aggregate_rates(filings)
store.apply("exclude_from_benchmark",
            {"filing": filings.primary_keys()[0], "reason": "under_review"},
            actor="you@example.org")
store.action_log[-1].to_json()
```

## Limits

- With the default fixture, Establishment and Filing objects are **synthetic**.
  They link to real ReportingYear and PeerGroup objects so the joins are
  exercised, but no number computed from fixture objects is a finding.
  `synthetic/README.md` explains the fixture.
- PeerGroup objects are the pooled 2016-2024 cells. Per-year cells
  (`peer_percentiles_by_year.csv`) are not modelled as objects.
- The store lives in memory, as plain Python dicts. It has been run on the
  fixture only. The `--data-dir` path uses the same loader as the pipeline, but
  it has not been run on the full real panel (2,801,064 filings), because the
  raw files are not in the repository.
- Actions are checked against the spec. There is no user or permission model:
  `actor` is whatever string the caller passes.

## Typed client generated from the spec

`src/ehs_osha/ontology/client.py` is generated from `spec.json` by
`scripts/generate_ontology_client.py` (code in `ontology/codegen.py`), in the
pattern of an ontology SDK. Object types become frozen dataclasses with typed
fields, links become methods returning typed object sets, and action types
become methods whose arguments are the action parameters, with `Literal` types
where the spec lists `allowed_values`.

```python
from ehs_osha.ontology.materialise import build_store
from ehs_osha.ontology.client import OntologyClient

client = OntologyClient(build_store())
bad = client.filings.where(screen_implausible=True)
sites = bad.establishment()          # EstablishmentSet
client.flag_filing_implausible(filing, "employee_count_mistyped", actor="analyst@example.org")
```

The generated file is committed. `python3 scripts/generate_ontology_client.py
--check` exits 1 when it no longer matches the spec; it runs in CI and in
`tests/test_ontology_client.py`, so a spec change that is not followed by
regeneration fails the build. Functions are not generated: they stay in
`functions.py`.
