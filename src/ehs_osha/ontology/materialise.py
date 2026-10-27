"""Build an :class:`ObjectStore` from pipeline data.

Two backing sources, kept apart by a ``source`` property on every object:

* **Establishment level** (Establishment, Filing): any harmonised frame from
  :func:`ehs_osha.load.load_ita_300a`. By default that is the SYNTHETIC
  fixture in ``synthetic/fixture``, because the real ITA files are not
  redistributed. Pass the real frame to get real objects.
* **Aggregate level** (ReportingYear, Sector, Industry, PeerGroup,
  QualityFlag): the committed pipeline outputs in ``outputs/tables``, which
  were computed from the real ITA files.

When the fixture is used, Filing objects link to real ReportingYear and
PeerGroup objects. That exercises the joins; it is not a comparison of real
sites, and nothing computed from fixture objects is a finding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

from .. import peers, quality
from ..catalog import DatasetFile
from ..load import load_ita_300a
from ..naics import naics3_title
from .runtime import ObjectStore
from .spec import OntologySpec

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "synthetic" / "fixture"
TABLES_DIR = ROOT / "outputs" / "tables"

SOURCE_FIXTURE = "synthetic_fixture"
SOURCE_RAW = "osha_ita_raw"
SOURCE_OUTPUTS = "osha_ita_committed_outputs"

#: Plain-language statement of each screen rule (bounds are the defaults in
#: :class:`ehs_osha.quality.PlausibilityConfig`).
_FLAG_TEXT = {
    "flag_hours_missing": "hours missing or <= 0",
    "flag_employees_missing": "employees missing or < 1",
    "flag_negative_counts": "negative case count",
    "flag_hours_per_employee_high": "hours per employee > {max:,.0f}",
    "flag_hours_per_employee_low": "hours per employee < {min:,.0f}",
    "flag_no_injury_contradiction": "'no injuries' box contradicts case counts",
}


def fixture_files(fixture_dir: Path = FIXTURE_DIR) -> List[DatasetFile]:
    """Catalog entries pointing at the SYNTHETIC fixture CSVs."""
    return [
        DatasetFile(
            key=f"synthetic_{p.stem.split('_')[-1]}",
            calendar_year=int(p.stem.split("_")[-1]),
            url="file://SYNTHETIC-NOT-A-REAL-SOURCE",
            local_name=p.name,
            note="SYNTHETIC FIXTURE. Not real data.",
        )
        for p in sorted(Path(fixture_dir).glob("SYNTHETIC_ITA_300A_*.csv"))
    ]


def load_fixture_frame(fixture_dir: Path = FIXTURE_DIR) -> pd.DataFrame:
    """Load the fixture through the same loader the real files use."""
    files = fixture_files(fixture_dir)
    if not files:
        raise FileNotFoundError(f"no fixture CSVs in {fixture_dir}; run make fixture")
    frame, _ = load_ita_300a(Path(fixture_dir), files=files)
    return frame


def _records(df: pd.DataFrame) -> Iterable[dict]:
    return df.to_dict(orient="records")


def filing_records(
    frame: pd.DataFrame,
    source: str,
    config: Optional[quality.PlausibilityConfig] = None,
) -> pd.DataFrame:
    """Screen and key a harmonised frame into Filing-shaped rows."""
    df = peers.add_peer_keys(quality.apply_screen(frame, config))
    df = df[df["establishment_id"].notna() & df["year_filing_for"].notna()].copy()
    df["establishment_id"] = df["establishment_id"].astype("int64").astype(str)
    df["year_filing_for"] = df["year_filing_for"].astype("int64")
    df["filing_id"] = df["establishment_id"] + "-" + df["year_filing_for"].astype(str)
    name = df["establishment_name"].astype("object").where(df["establishment_name"].notna(), df["establishment_id"])
    df["filing_title"] = name.astype(str) + " " + df["year_filing_for"].astype(str)
    df["peer_group_key"] = df["peer_group"]
    df["screen_implausible"] = df["implausible"].astype(bool)
    df["source"] = source
    return df


def build_store(
    spec: Optional[OntologySpec] = None,
    frame: Optional[pd.DataFrame] = None,
    tables_dir: Path = TABLES_DIR,
    source: str = SOURCE_FIXTURE,
    config: Optional[quality.PlausibilityConfig] = None,
    clock=None,
) -> ObjectStore:
    """Materialise every object type.

    Args:
        spec: Ontology spec; defaults to the bundled one.
        frame: Harmonised establishment frame; defaults to the fixture.
        tables_dir: Directory of committed pipeline tables.
        source: Provenance label for establishment-level objects.
        config: Screen bounds; defaults to the pipeline defaults.
        clock: Passed to :class:`ObjectStore`.

    Returns:
        A populated store.
    """
    from .functions import check_registry

    store = ObjectStore(spec, clock=clock)
    check_registry(store.spec.functions)
    cfg = config or quality.PlausibilityConfig()
    tables_dir = Path(tables_dir)
    if frame is None:
        frame = load_fixture_frame()

    filings = filing_records(frame, source, cfg)
    latest = filings.sort_values("year_filing_for").drop_duplicates("establishment_id", keep="last")
    store.add_objects("Establishment", _records(latest.assign(source=source)))
    store.add_objects("Filing", _records(filings))

    by_year = pd.read_csv(tables_dir / "quality_by_year.csv")
    by_year["year"] = by_year["label"].astype("int64")
    rates = pd.read_csv(tables_dir / "metrics_by_year.csv").rename(columns={"label": "year"})
    years = by_year.merge(rates[["year", "dart_screened", "ltir_screened", "severity_screened"]], on="year", how="left")
    years["year_label"] = "Reporting year " + years["year"].astype(str)
    store.add_objects("ReportingYear", _records(years.assign(source=SOURCE_OUTPUTS)))

    sectors = pd.read_csv(tables_dir / "quality_by_naics2.csv", dtype={"label": str})
    store.add_objects("Sector", _records(sectors.rename(columns={"label": "naics2"}).assign(source=SOURCE_OUTPUTS)))

    groups = pd.read_csv(tables_dir / "peer_percentiles_pooled.csv", dtype={"naics3": str})
    groups["peer_group_key"] = groups["naics3"] + "|" + groups["size_band"]
    store.add_objects("PeerGroup", _records(groups.assign(source=SOURCE_OUTPUTS)))

    codes = sorted(set(groups["naics3"]) | set(filings["naics3"].dropna().astype(str)))
    titles = [naics3_title(c) for c in codes]
    store.add_objects(
        "Industry",
        (
            {"naics3": c, "title": t or c, "has_official_title": t is not None, "naics2": c[:2], "source": SOURCE_OUTPUTS}
            for c, t in zip(codes, titles)
        ),
    )

    prev = pd.read_csv(tables_dir / "quality_flag_prevalence.csv").set_index("flag")
    flags = []
    for flag in quality.FLAG_COLUMNS:
        counts = flag != "flag_no_injury_contradiction" or cfg.treat_contradiction_as_implausible
        flags.append(
            {
                "flag": flag,
                "display_name": _FLAG_TEXT[flag].format(min=cfg.min_hours_per_employee, max=cfg.max_hours_per_employee),
                "counts_in_verdict": counts,
                "pooled_n": prev.loc[flag, "n"],
                "pooled_share": prev.loc[flag, "share"],
                "pooled_hours_share": prev.loc[flag, "hours_share"],
                "source": SOURCE_OUTPUTS,
            }
        )
    store.add_objects("QualityFlag", flags)
    return store
