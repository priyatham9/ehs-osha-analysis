"""Loading and harmonisation of OSHA ITA Form 300A files.

Reads the published zip archives (or bare CSVs), normalises headers, coerces
numeric fields, deduplicates amended filings, and derives the small number of
quantities the rest of the pipeline needs.

Deduplication matters and is easy to get wrong. An establishment can submit
more than one 300A record for the same reporting year (amendments carry a
``change_reason``). Across 2016-2024 there are 4,703 such duplicate
``(establishment_id, year_filing_for)`` pairs out of 2,805,767 raw rows. This
module keeps the row with the largest ``id`` within each pair, which is the
latest submission, and reports how many rows it dropped.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from . import schema
from .catalog import DatasetFile, all_files


class SchemaError(RuntimeError):
    """Raised when a published file lacks columns the pipeline requires."""


@dataclass
class LoadReport:
    """Bookkeeping for one load, so counts in the write-up are traceable."""

    rows_raw: int = 0
    rows_after_dedup: int = 0
    duplicate_rows_dropped: int = 0
    files_read: List[str] = field(default_factory=list)
    encodings_used: Dict[str, str] = field(default_factory=dict)
    columns_dropped: Dict[str, List[str]] = field(default_factory=dict)

    def to_json(self) -> dict:
        """Return a JSON-serialisable dict of this report."""
        return {
            "rows_raw": self.rows_raw,
            "rows_after_dedup": self.rows_after_dedup,
            "duplicate_rows_dropped": self.duplicate_rows_dropped,
            "files_read": self.files_read,
            "encodings_used": self.encodings_used,
            "columns_dropped": self.columns_dropped,
        }


def _read_csv_bytes(raw: bytes, label: str, report: LoadReport) -> pd.DataFrame:
    """Parse CSV bytes, trying each encoding in :data:`schema.ENCODING_FALLBACKS`.

    Args:
        raw: Full file contents.
        label: Name used in the load report.
        report: Report object updated in place.

    Returns:
        The parsed frame with normalised column names.

    Raises:
        SchemaError: If no encoding parses the file.
    """
    last: Optional[Exception] = None
    for enc in schema.ENCODING_FALLBACKS:
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding=enc, low_memory=False)
            report.encodings_used[label] = enc
            df.columns = schema.normalise_columns(df.columns)
            return df
        except UnicodeDecodeError as exc:
            last = exc
    df = pd.read_csv(
        io.BytesIO(raw), encoding="utf-8", encoding_errors="replace", low_memory=False
    )
    report.encodings_used[label] = "utf-8+replace"
    if last is not None:
        print(
            f"[WARN  ] {label}: not decodable as "
            f"{'/'.join(schema.ENCODING_FALLBACKS)}; read with replacement "
            f"characters. Text fields in this file may contain U+FFFD."
        )
    df.columns = schema.normalise_columns(df.columns)
    return df


def read_published_file(path: Path, report: LoadReport) -> pd.DataFrame:
    """Read one published ITA file (zip or CSV) into a normalised frame.

    Args:
        path: Path to a ``.zip`` containing exactly one CSV, or a ``.csv``.
        report: Report object updated in place.

    Returns:
        A frame restricted to the canonical schema columns present in the file.

    Raises:
        SchemaError: If required columns are absent, or a zip has no CSV member.
    """
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if len(members) != 1:
                raise SchemaError(
                    f"{path.name}: expected exactly one CSV member, found {members!r}"
                )
            raw = zf.read(members[0])
            label = f"{path.name}::{members[0]}"
    else:
        raw = path.read_bytes()
        label = path.name

    df = _read_csv_bytes(raw, label, report)
    missing = schema.missing_required(df.columns)
    if missing:
        raise SchemaError(f"{label}: missing required columns {missing!r}")

    keep = schema.select_canonical(df.columns)
    dropped = [c for c in df.columns if c not in keep]
    if dropped:
        report.columns_dropped[label] = dropped
    report.files_read.append(label)
    return df[keep].copy()


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce schema-numeric columns to float, turning junk into NaN.

    NaN is not treated as an error here. It is a plausibility-screen outcome,
    so that one unparsable cell does not abort a multi-million-row load and,
    more importantly, so that unparsable cells are *counted* rather than
    silently dropped.

    Args:
        df: Frame with normalised column names.

    Returns:
        A copy with numeric columns coerced.
    """
    out = df.copy()
    for col in schema.NUMERIC_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def derive_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived quantities the analysis depends on.

    Derived columns:

    ``recordable_cases``
        Sum of Form 300A columns G+H+I+J (deaths, days-away, job-transfer or
        restriction, other recordable). One row per case, no double counting.
    ``dart_cases``
        Sum of columns H+I.
    ``hours_per_employee``
        ``total_hours_worked / annual_average_employees``. The single most
        informative internal-consistency statistic in the file.
    ``trir``
        ``200000 * recordable_cases / total_hours_worked``, i.e. the
        establishment's own total recordable incident rate. Left as NaN when
        hours are non-positive or missing.
    ``dart_rate``
        ``200000 * dart_cases / total_hours_worked``.
    ``naics2`` / ``naics3`` / ``naics4``
        Zero-padded NAICS prefixes, as strings, for peer grouping.

    Args:
        df: Frame after :func:`coerce_numeric`.

    Returns:
        A copy with derived columns appended.
    """
    out = df.copy()
    rec_cols = [c for c in schema.RECORDABLE_COMPONENTS if c in out.columns]
    dart_cols = [c for c in schema.DART_COMPONENTS if c in out.columns]
    out["recordable_cases"] = out[rec_cols].sum(axis=1, min_count=len(rec_cols))
    out["dart_cases"] = out[dart_cols].sum(axis=1, min_count=len(dart_cols))

    emp = out["annual_average_employees"].where(out["annual_average_employees"] > 0)
    hours = out["total_hours_worked"]
    out["hours_per_employee"] = hours / emp

    pos_hours = hours.where(hours > 0)
    out["trir"] = 200000.0 * out["recordable_cases"] / pos_hours
    out["dart_rate"] = 200000.0 * out["dart_cases"] / pos_hours

    naics = out["naics_code"]
    naics_str = pd.Series(
        np.where(naics.notna(), naics.fillna(0).astype("int64").astype(str), ""),
        index=out.index,
        dtype="object",
    )
    # NAICS codes are 2-6 digits; pad short codes on the right is wrong, so only
    # take prefixes from codes that are long enough.
    # np.where(..., None) yields an object array whose missing value is None on
    # some numpy builds and nan on others, so the prefix columns are built with
    # pandas instead and the absent value is set to None explicitly. Callers and
    # tests can then rely on a single representation across versions.
    for n, name in ((2, "naics2"), (3, "naics3"), (4, "naics4")):
        prefix = naics_str.str[:n].astype(object)
        prefix[naics_str.str.len() < n] = None
        out[name] = prefix
    return out


def deduplicate(df: pd.DataFrame, report: LoadReport) -> pd.DataFrame:
    """Keep the latest filing per ``(establishment_id, year_filing_for)``.

    Amended 300A submissions appear as additional rows carrying a
    ``change_reason``. The row with the largest ``id`` is the most recent one.

    Args:
        df: Pooled frame across years.
        report: Report object updated in place.

    Returns:
        Deduplicated frame, index reset.
    """
    before = len(df)
    keys = ["establishment_id", "year_filing_for"]
    if not all(k in df.columns for k in keys):
        report.rows_after_dedup = before
        return df.reset_index(drop=True)
    sort_col = "id" if "id" in df.columns else keys[0]
    out = (
        df.sort_values(sort_col, kind="mergesort")
        .drop_duplicates(subset=keys, keep="last")
        .reset_index(drop=True)
    )
    report.duplicate_rows_dropped = before - len(out)
    report.rows_after_dedup = len(out)
    return out


def load_ita_300a(
    data_dir: Path,
    *,
    files: Optional[Iterable[DatasetFile]] = None,
    include_partial: bool = False,
    years: Optional[Sequence[int]] = None,
    dedup: bool = True,
) -> "tuple[pd.DataFrame, LoadReport]":
    """Load, pool, harmonise and deduplicate the ITA 300A files.

    Args:
        data_dir: Directory holding the raw downloads.
        files: Explicit catalog entries; defaults to :func:`catalog.all_files`.
        include_partial: Include partial-year files (2025). Off by default.
        years: If given, keep only these ``year_filing_for`` values.
        dedup: Apply :func:`deduplicate`.

    Returns:
        ``(frame, report)``. The frame carries canonical plus derived columns.

    Raises:
        FileNotFoundError: If a catalog file is not present locally.
        SchemaError: If a present file cannot be parsed against the schema.
    """
    data_dir = Path(data_dir)
    specs = list(files) if files is not None else all_files(include_partial)
    report = LoadReport()
    frames: List[pd.DataFrame] = []
    for spec in specs:
        path = data_dir / spec.local_name
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Run scripts/download_data.py first; this "
                f"loader does not fabricate missing years."
            )
        frames.append(read_published_file(path, report))

    pooled = pd.concat(frames, ignore_index=True, sort=False)
    report.rows_raw = len(pooled)
    pooled = coerce_numeric(pooled)
    if years is not None:
        pooled = pooled[pooled["year_filing_for"].isin(list(years))].copy()
    pooled = deduplicate(pooled, report) if dedup else pooled.reset_index(drop=True)
    if not dedup:
        report.rows_after_dedup = len(pooled)
    return derive_fields(pooled), report


def load_csv_fixture(path: Path) -> pd.DataFrame:
    """Load a single CSV in the ITA 300A layout (used for tests and fixtures).

    Args:
        path: CSV path.

    Returns:
        A harmonised frame with derived columns.

    Raises:
        SchemaError: If required columns are absent.
    """
    report = LoadReport()
    df = read_published_file(Path(path), report)
    df = coerce_numeric(df)
    df = deduplicate(df, report)
    return derive_fields(df)
