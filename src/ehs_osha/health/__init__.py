"""Portable data health: lineage spec, data expectations and generated docs.

This package mirrors two Foundry features without any platform dependency:

* ``lineage.json`` plus :mod:`ehs_osha.health.lineage` declare and validate
  the pipeline graph and render ``docs/LINEAGE.md`` (like Data Lineage).
* ``expectations.json`` plus :mod:`ehs_osha.health.expectations` check the
  committed output tables and render ``docs/DATA_HEALTH.md`` (like Data
  Health checks).

Run both with ``make health`` or ``PYTHONPATH=src python3 -m ehs_osha.health``.
"""
