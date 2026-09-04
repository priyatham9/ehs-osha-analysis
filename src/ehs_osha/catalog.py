"""Registry of the public OSHA Injury Tracking Application (ITA) files this
project consumes.

Every entry here was resolved by fetching https://www.osha.gov/itadata and
reading the anchor hrefs on that page. URLs, byte sizes and SHA-256 digests were
verified by download on 2026-09-03. OSHA revises published files in place
(the 2025 summary file already carries a ``_v2`` suffix), so a digest mismatch
is reported as a warning with the observed digest, not silently ignored and not
silently accepted.

Nothing in this module fabricates or substitutes data. If a file cannot be
retrieved the downloader raises; see :mod:`ehs_osha.download`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

ITA_LANDING_PAGE = "https://www.osha.gov/itadata"

#: OSHA's CDN rejects requests without a browser-style User-Agent (HTTP 403).
#: This is a documented access quirk, not an attempt to disguise the client.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class DatasetFile:
    """One published OSHA ITA Form 300A summary file.

    Attributes:
        key: Short stable identifier used for local filenames and manifests.
        calendar_year: The reporting year the filing covers (``year_filing_for``).
        url: Fully-qualified public download URL (no API key required).
        local_name: Filename used when stored under ``data/raw``.
        expected_bytes: Content-Length observed on 2026-09-03, or ``None``.
        expected_sha256: SHA-256 observed on 2026-09-03, or ``None`` if the file
            has not yet been retrieved and pinned.
        note: Free-text provenance note.
    """

    key: str
    calendar_year: int
    url: str
    local_name: str
    expected_bytes: Optional[int] = None
    expected_sha256: Optional[str] = None
    note: str = ""


ITA_300A_FILES: Tuple[DatasetFile, ...] = (
    DatasetFile(
        key="ita_300a_2016",
        calendar_year=2016,
        url="https://www.osha.gov/sites/default/files/ITA%20Data%20CY%202016.zip",
        local_name="ITA_Data_CY_2016.zip",
        expected_bytes=12106381,
        expected_sha256="9f41c720fb02f78788f1090e5fc885fdb09343fc349c4ae4c80cc9165d83742f",
        note="First ITA collection year.",
    ),
    DatasetFile(
        key="ita_300a_2017",
        calendar_year=2017,
        url="https://www.osha.gov/sites/default/files/ITA%20Data%20CY%202017.zip",
        local_name="ITA_Data_CY_2017.zip",
        expected_bytes=14682864,
        expected_sha256="354fb246be90d6bac3d4a7c94e44f90d40f1d3ff73f911d37691ae98a87de0fb",
    ),
    DatasetFile(
        key="ita_300a_2018",
        calendar_year=2018,
        url="https://www.osha.gov/sites/default/files/ITA%20Data%20CY%202018.zip",
        local_name="ITA_Data_CY_2018.zip",
        expected_bytes=16970794,
        expected_sha256="0bd2e8475a5766baba8883a1258a92168c43c5ff551c853b1992641814b4dc2f",
        note="Contains bytes that are not valid UTF-8; loader falls back per schema.py.",
    ),
    DatasetFile(
        key="ita_300a_2019",
        calendar_year=2019,
        url="https://www.osha.gov/sites/default/files/ITA%20Data%20CY%202019.zip",
        local_name="ITA_Data_CY_2019.zip",
        expected_bytes=18898257,
        expected_sha256="bf93ea7312bfe34d903c1272f15c785a61b8c8bbc6df6e09f0d3fe372205ac6e",
    ),
    DatasetFile(
        key="ita_300a_2020",
        calendar_year=2020,
        url="https://www.osha.gov/sites/default/files/ITA-Data-CY-2020.zip",
        local_name="ITA_Data_CY_2020.zip",
        expected_bytes=19480392,
        expected_sha256="eb704f2cc343adc7710b48204015ac11c3018fae684f44747158d731e713899b",
    ),
    DatasetFile(
        key="ita_300a_2021",
        calendar_year=2021,
        url="https://www.osha.gov/sites/default/files/ITA-data-cy2021.zip",
        local_name="ITA_Data_CY_2021.zip",
        expected_bytes=19431073,
        expected_sha256="5a11abc7c085f07f08f130c25bf78c85581b2379fb8b514f728bfcdf5d61b4a3",
    ),
    DatasetFile(
        key="ita_300a_2022",
        calendar_year=2022,
        url="https://www.osha.gov/sites/default/files/ITA-data-cy2022.zip",
        local_name="ITA_Data_CY_2022.zip",
        expected_bytes=19730409,
        expected_sha256="e396af8038d40d74b96ebb6ee9b561bbcb8907ee66adff089402a676c919e6ef",
    ),
    DatasetFile(
        key="ita_300a_2023",
        calendar_year=2023,
        url=(
            "https://www.osha.gov/sites/default/files/"
            "ITA_300A_Summary_Data_2023_through_12-31-2024.zip"
        ),
        local_name="ITA_300A_Summary_Data_2023_through_12-31-2024.zip",
        expected_bytes=24143043,
        expected_sha256="25da8bc426db219a7a5fe872e73830afebdfac87c460f8cf6561658e7103b487",
        note="Archive member is a '_v2' revision; 'size' field recoding starts this year.",
    ),
    DatasetFile(
        key="ita_300a_2024",
        calendar_year=2024,
        url=(
            "https://www.osha.gov/sites/default/files/"
            "ITA_300A_Summary_Data_2024_through_12-31-2025.zip"
        ),
        local_name="ITA_300A_Summary_Data_2024_through_12-31-2025.zip",
        expected_bytes=23855931,
        expected_sha256="4cbce7ea32dd4060f442a528670936e552d1b731925f320d9d25a168f9b60b1d",
    ),
)

#: Files published as a bare CSV rather than a zip. Kept separate because the
#: 2025 file is a partial year (collection through 2026-03-15) and must not be
#: pooled with complete years without an explicit decision.
ITA_300A_PARTIAL_FILES: Tuple[DatasetFile, ...] = (
    DatasetFile(
        key="ita_300a_2025_partial",
        calendar_year=2025,
        url=(
            "https://www.osha.gov/sites/default/files/"
            "ITA_300A_Summary_Data_2025_through_03-15-2026_v2.csv"
        ),
        local_name="ITA_300A_Summary_Data_2025_through_03-15-2026_v2.csv",
        expected_bytes=84600899,
        expected_sha256=None,
        note=(
            "PARTIAL YEAR: collection was still open at publication. Excluded "
            "from the default pipeline; opt in with --include-partial."
        ),
    ),
)

#: Supporting documentation. Not parsed by this project, but recorded so the
#: provenance chain is complete and a reader can check field definitions.
DOCUMENTATION_URLS: Dict[str, str] = {
    "summary_data_dictionary": (
        "https://www.osha.gov/sites/default/files/summary_data_dictionary.pdf"
    ),
    "ita_data_users_guide": (
        "https://www.osha.gov/sites/default/files/ITA_data_users_guide.pdf"
    ),
    "ita_data_dictionary": (
        "https://www.osha.gov/sites/default/files/ITA_Data_Dictionary.pdf"
    ),
    "osha_vs_bls_comparison": (
        "https://www.osha.gov/sites/default/files/"
        "ComparisonBetweenOSHAITA_Data_and_BLS_SOII_Estimates.pdf"
    ),
}


def all_files(include_partial: bool = False) -> List[DatasetFile]:
    """Return the catalog entries the pipeline should process.

    Args:
        include_partial: If True, append partial-year files (currently 2025).
            These are excluded by default because their collection window was
            still open when published, so counts are not comparable to complete
            years.

    Returns:
        A list of :class:`DatasetFile` in calendar-year order.
    """
    files = list(ITA_300A_FILES)
    if include_partial:
        files.extend(ITA_300A_PARTIAL_FILES)
    return sorted(files, key=lambda f: f.calendar_year)


def by_key(key: str) -> DatasetFile:
    """Look up a catalog entry by its ``key``.

    Args:
        key: Catalog key, e.g. ``"ita_300a_2019"``.

    Returns:
        The matching :class:`DatasetFile`.

    Raises:
        KeyError: If no entry has that key.
    """
    for f in all_files(include_partial=True):
        if f.key == key:
            return f
    raise KeyError(f"unknown catalog key: {key!r}")
