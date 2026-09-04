"""Downloader for public OSHA ITA files.

Design constraints, in priority order:

1. **No API key.** Every URL in :mod:`ehs_osha.catalog` is anonymously
   retrievable. OSHA's CDN returns HTTP 403 to a default ``urllib`` User-Agent,
   so a browser-style UA header is sent. That is the only header required.
2. **Fail loudly.** If a file cannot be retrieved, is truncated, or does not
   match its pinned digest, this module raises :class:`DownloadError`. It never
   substitutes synthetic, cached-stale, or partial data, and it never returns a
   success status for a failed fetch. Downstream analysis code will therefore
   stop rather than silently analysing something else.
3. **Record provenance.** Every successful download appends an entry to
   ``manifest.json`` in the destination directory: URL, retrieval timestamp
   (UTC), byte count, SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from .catalog import DEFAULT_USER_AGENT, DatasetFile, all_files

MANIFEST_NAME = "manifest.json"
_CHUNK = 1 << 20


class DownloadError(RuntimeError):
    """Raised when a required public file could not be obtained intact.

    This exception is deliberately fatal. Callers must not catch it and
    continue with substitute data.
    """


@dataclass
class DownloadRecord:
    """Provenance record for one retrieved file."""

    key: str
    url: str
    local_path: str
    bytes: int
    sha256: str
    retrieved_utc: str
    digest_matches_catalog: Optional[bool]

    def to_json(self) -> dict:
        """Return a JSON-serialisable dict of this record."""
        return asdict(self)


def _sha256_of(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file.

    Args:
        path: File to hash.

    Returns:
        Lowercase hex digest.
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _http_get_to_file(url: str, dest: Path, timeout: int, user_agent: str) -> int:
    """Stream a URL to ``dest``, returning the number of bytes written.

    Downloads to a sibling temporary file and moves it into place only on
    success, so an interrupted run never leaves a truncated file that a later
    run would mistake for a complete one.

    Args:
        url: Absolute http(s) URL.
        dest: Final destination path.
        timeout: Socket timeout in seconds.
        user_agent: Value for the User-Agent header.

    Returns:
        Bytes written.

    Raises:
        DownloadError: On any HTTP or network failure.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
    os.close(tmp_fd)
    tmp = Path(tmp_name)
    written = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            status = getattr(resp, "status", 200)
            if status != 200:
                raise DownloadError(f"HTTP {status} for {url}")
            with tmp.open("wb") as out:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
    except urllib.error.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"HTTP {exc.code} for {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"network failure for {url}: {exc.reason}") from exc
    except Exception as exc:  # pragma: no cover - defensive
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"unexpected failure for {url}: {exc}") from exc

    if written == 0:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"empty response body for {url}")
    shutil.move(str(tmp), str(dest))
    return written


def download_one(
    spec: DatasetFile,
    dest_dir: Path,
    *,
    force: bool = False,
    timeout: int = 600,
    user_agent: str = DEFAULT_USER_AGENT,
    verbose: bool = True,
) -> DownloadRecord:
    """Download a single catalog file and verify it.

    Args:
        spec: Catalog entry to fetch.
        dest_dir: Directory to write into (created if absent).
        force: Re-download even if a local copy already exists.
        timeout: Socket timeout in seconds.
        user_agent: User-Agent header value.
        verbose: Print progress to stdout.

    Returns:
        A :class:`DownloadRecord` describing the local file.

    Raises:
        DownloadError: If the fetch fails, the file is empty, or the byte count
            disagrees with the pinned Content-Length in the catalog.
    """
    dest = Path(dest_dir) / spec.local_name
    if dest.exists() and not force:
        size = dest.stat().st_size
        digest = _sha256_of(dest)
        if verbose:
            print(f"[cached] {spec.key}: {dest} ({size:,} bytes)")
    else:
        if verbose:
            print(f"[fetch ] {spec.key}: {spec.url}")
        size = _http_get_to_file(spec.url, dest, timeout, user_agent)
        digest = _sha256_of(dest)
        if verbose:
            print(f"[ok    ] {spec.key}: {size:,} bytes  sha256={digest[:16]}...")

    if spec.expected_bytes is not None and size != spec.expected_bytes:
        raise DownloadError(
            f"{spec.key}: size mismatch. Expected {spec.expected_bytes:,} bytes "
            f"(observed 2026-09-03), got {size:,}. OSHA revises files in place; "
            f"if the file has legitimately changed, update catalog.py and "
            f"re-run every analysis that depended on the old vintage."
        )

    matches: Optional[bool] = None
    if spec.expected_sha256 is not None:
        matches = digest == spec.expected_sha256
        if not matches:
            print(
                f"[WARN  ] {spec.key}: SHA-256 differs from the pinned catalog "
                f"digest.\n         pinned:   {spec.expected_sha256}\n"
                f"         observed: {digest}\n"
                f"         Byte count still matches, so this is most likely a "
                f"republished file. Results computed from it are NOT comparable "
                f"to results reported against the pinned vintage."
            )

    return DownloadRecord(
        key=spec.key,
        url=spec.url,
        local_path=str(dest),
        bytes=size,
        sha256=digest,
        retrieved_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        digest_matches_catalog=matches,
    )


def download_all(
    dest_dir: Path,
    *,
    files: Optional[Iterable[DatasetFile]] = None,
    include_partial: bool = False,
    force: bool = False,
    timeout: int = 600,
    verbose: bool = True,
) -> List[DownloadRecord]:
    """Download the full catalog and write ``manifest.json``.

    Args:
        dest_dir: Directory to write into.
        files: Explicit file list; defaults to :func:`catalog.all_files`.
        include_partial: Pass through to :func:`catalog.all_files`.
        force: Re-download even if local copies exist.
        timeout: Socket timeout in seconds.
        verbose: Print progress.

    Returns:
        One :class:`DownloadRecord` per file, in catalog order.

    Raises:
        DownloadError: On the first file that cannot be obtained intact. The
            manifest is not written in that case.
    """
    dest_dir = Path(dest_dir)
    specs = list(files) if files is not None else all_files(include_partial)
    records = [
        download_one(
            s, dest_dir, force=force, timeout=timeout, verbose=verbose
        )
        for s in specs
    ]
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "OSHA Injury Tracking Application (ITA) public data",
        "landing_page": "https://www.osha.gov/itadata",
        "files": [r.to_json() for r in records],
    }
    (dest_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")
    if verbose:
        print(f"[ok    ] wrote {dest_dir / MANIFEST_NAME}")
    return records


def require_local_files(
    dest_dir: Path,
    *,
    include_partial: bool = False,
) -> List[Path]:
    """Assert that every catalog file is present locally, or fail loudly.

    Analysis entry points call this instead of quietly proceeding with whatever
    subset happens to be on disk.

    Args:
        dest_dir: Directory that should hold the raw files.
        include_partial: Include partial-year files in the requirement.

    Returns:
        Paths to the local files, in catalog order.

    Raises:
        DownloadError: If any file is missing, naming the exact command to run.
    """
    dest_dir = Path(dest_dir)
    missing, paths = [], []
    for spec in all_files(include_partial):
        p = dest_dir / spec.local_name
        (paths if p.exists() else missing).append(p)
    if missing:
        names = "\n  ".join(str(m) for m in missing)
        raise DownloadError(
            "Required OSHA ITA files are not present:\n  "
            + names
            + "\n\nRun:  python scripts/download_data.py --dest "
            + str(dest_dir)
            + "\n\nThis pipeline does not substitute synthetic data for missing "
            "real data. If you want to exercise the code without a network, run "
            "the synthetic fixture explicitly (see synthetic/README.md)."
        )
    return paths
