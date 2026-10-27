# Changelog

All notable changes to this project are documented here. The format follows
Keep a Changelog and this project uses semantic versioning.

## [Unreleased]

### Added
- Establishment linkage and panel-quality audit (`panel_audit.py`, `scripts/run_panel_audit.py`, `outputs/tables/panel_linkage_audit.csv`, `docs/PANEL_AUDIT.md`): years-present distribution, adjacent-year linkage, id attribute drift, and bounds on where the 29.7x correction sits, built from committed tables only, with the unanswerable questions marked as such
- `src/ehs_osha/health/`: data expectations as code (260 checks with id, severity, scope and rationale over `outputs/tables/*.csv` and `outputs/summary.json`) and a validated pipeline lineage spec; `make health` regenerates `docs/DATA_HEALTH.md` and `docs/LINEAGE.md` (Mermaid graph), exits nonzero on error-severity failures; `tests/test_health.py` checks the docs are current and that corrupted table copies fail
- Typed ontology client generated from `spec.json` (`ontology/codegen.py`, `ontology/client.py`, `scripts/generate_ontology_client.py`) with a drift check in CI and tests
- Rate detectability planner (`detectability.py`, `scripts/run_detectability.py`, `outputs/tables/detectability_by_size_band.csv`): exact Poisson intervals and site-years needed to distinguish two TRIRs per size band, with methods note `docs/DETECTABILITY.md`
- Browser Form 300A filing checker (`docs/filing_check.html`) driven by a shared JSON rule spec (`src/ehs_osha/plausibility_rules.json`) evaluated by Python (`filing_check.py`) and JavaScript, with a parity test against `quality.apply_screen`
- `src/ehs_osha/ontology/`: Foundry-style ontology (JSON spec of object, link and action types and functions; validating runtime with link traversal, actions and an action log; SQLite/JSON export) on public data, documented in `docs/ontology.md`

## [0.1.0] - 2026-09-09

### Added
- Reproducible pipeline over public OSHA Injury Tracking Application Form 300A establishment filings from 2016-2024 (2.8M filings)
- Plausibility screen identifying implausible filings by hours per employee, missing values, and case count consistency
- Comprehensive analysis showing screened aggregate TRIR stable at 3.98 across 9 years while unscreened varies 1.39x to 249x depending on year composition
- Count model comparison (Poisson, NB2, ZIP, ZINB) demonstrating overdispersion is universal and zero-inflation optional across 30 largest industries
- Peer-group analysis by NAICS 3-digit and establishment size band with percentile stability measured by Spearman rank correlation and absolute relative change
- Sensitivity grid demonstrating screened rate insensitive to plausibility threshold choice while flagged share moves by design
