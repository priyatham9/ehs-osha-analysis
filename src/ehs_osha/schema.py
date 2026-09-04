"""Canonical schema for OSHA ITA Form 300A establishment summary records.

The published CSVs are broadly consistent in *column names* across 2016-2024,
but not in column *order*, not in encoding, and not in the semantics of every
field. Three drift issues are handled here and documented because each one is a
silent-wrong-answer trap:

1. **Column order changes** between the 2016-2022 files and the 2023+ files, and
   ``naics_year`` appears only from 2023. Positional reads break; name-based
   reads do not.
2. **Encoding.** ``ITA Data CY 2018.csv`` contains bytes that are not valid
   UTF-8 (e.g. 0x92, a Windows-1252 right single quote). Reading it as strict
   UTF-8 raises. The loader retries with cp1252 and finally with replacement.
3. **The ``size`` field is not comparable across years.** OSHA's summary data
   dictionary (April 2024) documents the codes as 1 = <20 employees,
   2 = 20-249, 21 = 20-99, 22 = 100-249, 3 = 250+, and notes that "code 2 was
   split to 21 and 22 with the collection of 2023 data". The published files
   bear that out: codes 21 and 22 first appear in 2022 (292 filings) and take
   over in 2023, and median ``annual_average_employees`` is 51 for code 2, 39
   for code 21 and 138 for code 22. So the codes are documented, but a raw
   ``size`` value still does not mean the same thing in 2019 as in 2024, and
   the old and new codes coexist in the pooled panel. ``size`` is therefore
   carried through but never used for peer grouping; size bands are derived
   from ``annual_average_employees`` instead (see :mod:`ehs_osha.peers`), which
   is defined identically in every year.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

#: Identity and location fields retained for grouping and traceability.
ID_COLUMNS: Sequence[str] = (
    "id",
    "establishment_id",
    "ein",
    "company_name",
    "establishment_name",
    "city",
    "state",
    "zip_code",
)

#: Fields describing what kind of establishment filed.
CONTEXT_COLUMNS: Sequence[str] = (
    "naics_code",
    "naics_year",
    "industry_description",
    "establishment_type",
    "size",
    "year_filing_for",
    "created_timestamp",
    "change_reason",
)

#: Numeric fields from the Form 300A summary itself.
MEASURE_COLUMNS: Sequence[str] = (
    "annual_average_employees",
    "total_hours_worked",
    "no_injuries_illnesses",
    "total_deaths",
    "total_dafw_cases",
    "total_djtr_cases",
    "total_other_cases",
    "total_dafw_days",
    "total_djtr_days",
    "total_injuries",
    "total_skin_disorders",
    "total_respiratory_conditions",
    "total_poisonings",
    "total_hearing_loss",
    "total_other_illnesses",
)

CANONICAL_COLUMNS: Sequence[str] = tuple(ID_COLUMNS) + tuple(CONTEXT_COLUMNS) + tuple(
    MEASURE_COLUMNS
)

#: Columns coerced with ``pd.to_numeric(errors="coerce")``. Coercion failures
#: become NaN and are then caught by the plausibility screen rather than by an
#: exception, so a single malformed cell cannot abort a 2.8M-row load.
NUMERIC_COLUMNS: Sequence[str] = tuple(MEASURE_COLUMNS) + (
    "naics_code",
    "naics_year",
    "establishment_type",
    "size",
    "year_filing_for",
    "establishment_id",
    "id",
)

#: Case-count columns whose sum is the OSHA total recordable case count.
#: 29 CFR 1904.7 defines a recordable case as death, days away from work,
#: restricted work or job transfer, medical treatment beyond first aid, loss of
#: consciousness, or a significant diagnosis. On Form 300A those partition into
#: columns (G) deaths, (H) days away, (I) job transfer/restriction and (J) other
#: recordable cases. Summing the four counts each case exactly once.
RECORDABLE_COMPONENTS: Sequence[str] = (
    "total_deaths",
    "total_dafw_cases",
    "total_djtr_cases",
    "total_other_cases",
)

#: DART = days away, restricted or transferred (columns H + I).
DART_COMPONENTS: Sequence[str] = ("total_dafw_cases", "total_djtr_cases")

#: Encodings tried in order when reading a published CSV.
ENCODING_FALLBACKS: Sequence[str] = ("utf-8", "cp1252")

#: Values of ``no_injuries_illnesses``. Determined empirically by cross-tabbing
#: the field against ``recordable_cases == 0`` over 2.80M deduplicated filings:
#: code 1 co-occurs with a positive case count 1,748,158 times and with zero
#: cases 199 times; code 2 co-occurs with zero cases 1,052,604 times and with a
#: positive count 102 times. The 301 contradictions are surfaced by the
#: plausibility screen as ``flag_no_injury_contradiction``.
NO_INJURY_FLAG_MEANING: Dict[int, str] = {
    1: "filer indicated cases occurred",
    2: "filer indicated no cases occurred",
}


def normalise_columns(columns: Sequence[str]) -> List[str]:
    """Strip whitespace and lowercase raw CSV header names.

    Args:
        columns: Header names exactly as read from the CSV.

    Returns:
        Cleaned header names, in the same order.
    """
    return [str(c).strip().lower() for c in columns]


def select_canonical(columns: Sequence[str]) -> List[str]:
    """Intersect a file's columns with the canonical schema, preserving order.

    Args:
        columns: Normalised column names present in a file.

    Returns:
        The canonical columns actually available in that file.
    """
    present = set(columns)
    return [c for c in CANONICAL_COLUMNS if c in present]


def missing_required(columns: Sequence[str]) -> List[str]:
    """Report canonical columns that a file must have but does not.

    Args:
        columns: Normalised column names present in a file.

    Returns:
        Names of required columns that are absent. Empty list means usable.
    """
    required = (
        "establishment_id",
        "naics_code",
        "annual_average_employees",
        "total_hours_worked",
        "year_filing_for",
    ) + tuple(RECORDABLE_COMPONENTS)
    present = set(columns)
    return [c for c in required if c not in present]
