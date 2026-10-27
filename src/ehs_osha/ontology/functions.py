"""Ontology functions: thin adapters over the pipeline's own metric code.

Nothing here re-implements a rate or a screen. Each function turns objects back
into the frame shape the pipeline already understands and calls the module the
spec names under ``reuses``:

=================== ====================================
function            reuses
=================== ====================================
plausibility_screen ``ehs_osha.quality.apply_screen``
filing_rates        ``ehs_osha.load.derive_fields``
aggregate_trir      ``ehs_osha.quality.aggregate_trir``
aggregate_rates     ``ehs_osha.metrics.compute_rates``
peer_position       ``ehs_osha.peers.DEFAULT_PERCENTILES``
=================== ====================================

"Included" in an aggregate means: passes the screen, and carries neither an
analyst flag nor a benchmark exclusion. That is how action writeback reaches
the numbers.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional

import numpy as np
import pandas as pd

from .. import load, metrics, peers, quality
from .runtime import ObjectSet, ObjectStore, OntologyObject


def _filing_frame(filings: ObjectSet, respect_writeback: bool = True) -> pd.DataFrame:
    """Frame of filings with an ``implausible`` column the pipeline understands."""
    if filings.object_type != "Filing":
        raise TypeError(f"expected an ObjectSet<Filing>, got ObjectSet<{filings.object_type}>")
    df = filings.to_frame()
    excluded = df["screen_implausible"].astype(bool)
    if respect_writeback:
        excluded = excluded | df["analyst_flag"].astype(bool) | df["benchmark_excluded"].astype(bool)
    df["implausible"] = excluded.to_numpy(dtype=bool)
    for col in ("total_hours_worked", "recordable_cases", *sum(metrics.RATE_NUMERATORS.values(), [])):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df


def plausibility_screen(
    filings: ObjectSet, config: Optional[quality.PlausibilityConfig] = None
) -> Dict[Any, bool]:
    """Re-run :func:`ehs_osha.quality.apply_screen` on a set under any bounds.

    Returns:
        filing_id -> implausible verdict. Objects are not edited.
    """
    df = filings.to_frame()
    for col in ("total_hours_worked", "annual_average_employees", "hours_per_employee", "recordable_cases"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    out = quality.apply_screen(df, config)
    return dict(zip(df["filing_id"], out["implausible"].astype(bool)))


def filing_rates(filing: OntologyObject) -> Dict[str, float]:
    """Re-derive one filing's TRIR and DART rate with :func:`load.derive_fields`."""
    row = {k: filing[k] for k in ("total_hours_worked", "annual_average_employees", "naics_code")}
    for c in metrics.RATE_NUMERATORS["trir"]:
        row[c] = filing[c]
    frame = pd.DataFrame([row])
    frame["naics_code"] = pd.to_numeric(frame["naics_code"], errors="coerce")
    for c in frame.columns:
        frame[c] = pd.to_numeric(frame[c], errors="coerce").astype("float64")
    derived = load.derive_fields(frame).iloc[0]
    return {"trir": float(derived["trir"]), "dart_rate": float(derived["dart_rate"])}


def aggregate_trir(filings: ObjectSet, respect_writeback: bool = True) -> float:
    """Ratio-of-sums TRIR over included filings via :func:`quality.aggregate_trir`."""
    df = _filing_frame(filings, respect_writeback)
    keep = df[~df["implausible"]]
    return quality.aggregate_trir(keep["recordable_cases"], keep["total_hours_worked"])


def aggregate_rates(
    filings: ObjectSet, respect_writeback: bool = True, label: str = "object_set"
) -> Dict[str, object]:
    """Screened and unscreened TRIR, DART, LTIR, severity via :func:`metrics.compute_rates`."""
    return metrics.compute_rates(_filing_frame(filings, respect_writeback), label=label)


def peer_position(store: ObjectStore, filing: OntologyObject) -> Dict[str, Any]:
    """Place a filing's TRIR within its pooled peer group's percentiles.

    Returns:
        ``status`` is ``"placed"`` with a ``band`` such as ``"p50-p75"``
        (``"<p10"`` and ``">=p95"`` at the ends), or a reason it was not
        placed: ``excluded`` (screen or writeback), ``no_rate``,
        ``no_peer_group`` or ``not_publishable``.
    """
    base = {"filing_id": filing.primary_key, "peer_group_key": filing["peer_group_key"], "band": None}
    if filing["screen_implausible"] or filing["analyst_flag"] or filing["benchmark_excluded"]:
        return {**base, "status": "excluded"}
    trir = filing["trir"]
    if trir is None or not math.isfinite(trir):
        return {**base, "status": "no_rate"}
    group = store.linked(filing, "peer_group").one()
    if group is None:
        return {**base, "status": "no_peer_group"}
    if not group["publishable"]:
        return {**base, "status": "not_publishable"}
    names = [f"p{q:g}" for q in peers.DEFAULT_PERCENTILES]
    cuts = np.array([group[n] for n in names], dtype="float64")
    i = int(np.searchsorted(cuts, trir, side="right"))
    band = "<" + names[0] if i == 0 else ">=" + names[-1] if i == len(names) else f"{names[i - 1]}-{names[i]}"
    return {**base, "status": "placed", "band": band}


#: Function api_name -> implementation. Checked against the spec by
#: :func:`check_registry` so the two cannot drift apart.
REGISTRY: Dict[str, Callable[..., Any]] = {
    "plausibility_screen": plausibility_screen,
    "filing_rates": filing_rates,
    "aggregate_trir": aggregate_trir,
    "aggregate_rates": aggregate_rates,
    "peer_position": peer_position,
}


def check_registry(spec_functions: Dict[str, Dict[str, Any]]) -> None:
    """Raise if the spec and :data:`REGISTRY` disagree on the function set."""
    missing = set(spec_functions) - set(REGISTRY)
    extra = set(REGISTRY) - set(spec_functions)
    if missing or extra:
        raise ValueError(f"function registry mismatch: missing={sorted(missing)} extra={sorted(extra)}")
