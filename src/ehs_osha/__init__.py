"""Reproducible analysis of public OSHA Injury Tracking Application data.

The package is organised so that each stage can be used on its own:

``catalog``      Registry of the public OSHA files, with pinned sizes/digests.
``download``     Key-free downloader that fails loudly and records provenance.
``schema``       Canonical column set and the documented schema drifts.
``load``         Reading, harmonisation, deduplication and derived fields.
``quality``      The plausibility screen and its effect on aggregate rates.
``peers``        NAICS x size-band peer groups and percentile tables.
``optimize``     Nelder-Mead and golden-section, since SciPy is not available.
``countmodels``  Poisson / NB2 / ZIP / ZINB maximum-likelihood fits.
``stability``    Year-over-year stability of percentile bands.
``svgplot``      Minimal SVG figure writer, since matplotlib is not available.
``pipeline``     End-to-end orchestration; writes every table and figure.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "catalog",
    "countmodels",
    "download",
    "load",
    "optimize",
    "peers",
    "pipeline",
    "quality",
    "schema",
    "stability",
    "svgplot",
]
