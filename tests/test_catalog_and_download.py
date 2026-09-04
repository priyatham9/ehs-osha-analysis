"""Tests for the dataset catalog and the fail-loud downloader.

The HTTP tests run against a local ``http.server`` on an ephemeral port, so they
exercise the real urllib code path (including 404 handling and truncation
detection) without touching the network.
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path

import _context  # noqa: F401

from ehs_osha.catalog import (
    DatasetFile,
    ITA_300A_FILES,
    all_files,
    by_key,
)
from ehs_osha.download import (
    DownloadError,
    _sha256_of,
    download_all,
    download_one,
    require_local_files,
)


class LocalServer:
    """Context manager serving a directory over HTTP on an ephemeral port."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.httpd: socketserver.TCPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> "LocalServer":
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            """SimpleHTTPRequestHandler without per-request stderr logging."""

            def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
                return

        handler = functools.partial(QuietHandler, directory=str(self.directory))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    @property
    def base(self) -> str:
        """Base URL of the running server."""
        assert self.httpd is not None
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __exit__(self, *exc: object) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()


class TestCatalog(unittest.TestCase):
    """The catalog must be internally consistent and unambiguous."""

    def test_keys_are_unique(self) -> None:
        keys = [f.key for f in all_files(include_partial=True)]
        self.assertEqual(len(keys), len(set(keys)))

    def test_years_are_unique_and_sorted(self) -> None:
        years = [f.calendar_year for f in all_files()]
        self.assertEqual(years, sorted(years))
        self.assertEqual(len(years), len(set(years)))

    def test_urls_are_https_osha(self) -> None:
        for f in all_files(include_partial=True):
            self.assertTrue(f.url.startswith("https://www.osha.gov/"), f.url)

    def test_every_complete_year_is_pinned(self) -> None:
        for f in ITA_300A_FILES:
            self.assertIsNotNone(f.expected_bytes, f.key)
            self.assertIsNotNone(f.expected_sha256, f.key)
            self.assertEqual(len(f.expected_sha256 or ""), 64, f.key)

    def test_partial_year_excluded_by_default(self) -> None:
        default_years = {f.calendar_year for f in all_files()}
        with_partial = {f.calendar_year for f in all_files(include_partial=True)}
        self.assertNotIn(2025, default_years)
        self.assertIn(2025, with_partial)

    def test_by_key_raises_on_unknown(self) -> None:
        self.assertEqual(by_key("ita_300a_2019").calendar_year, 2019)
        with self.assertRaises(KeyError):
            by_key("no_such_key")


class TestDownloadFailsLoudly(unittest.TestCase):
    """The downloader must never silently produce or accept substitute data."""

    def test_missing_files_raise_with_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(DownloadError) as ctx:
                require_local_files(Path(td))
            msg = str(ctx.exception)
            self.assertIn("scripts/download_data.py", msg)
            self.assertIn("does not substitute synthetic data", msg)

    def test_http_404_raises(self) -> None:
        with tempfile.TemporaryDirectory() as srv, tempfile.TemporaryDirectory() as dst:
            with LocalServer(Path(srv)) as s:
                spec = DatasetFile(
                    key="missing",
                    calendar_year=1999,
                    url=f"{s.base}/not_there.zip",
                    local_name="not_there.zip",
                )
                with self.assertRaises(DownloadError):
                    download_one(spec, Path(dst), verbose=False)
                self.assertFalse((Path(dst) / "not_there.zip").exists())

    def test_size_mismatch_raises_and_names_the_cause(self) -> None:
        with tempfile.TemporaryDirectory() as srv, tempfile.TemporaryDirectory() as dst:
            payload = b"x" * 100
            (Path(srv) / "f.bin").write_bytes(payload)
            with LocalServer(Path(srv)) as s:
                spec = DatasetFile(
                    key="wrong_size",
                    calendar_year=1999,
                    url=f"{s.base}/f.bin",
                    local_name="f.bin",
                    expected_bytes=999,
                )
                with self.assertRaises(DownloadError) as ctx:
                    download_one(spec, Path(dst), verbose=False)
                self.assertIn("size mismatch", str(ctx.exception))

    def test_successful_download_records_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as srv, tempfile.TemporaryDirectory() as dst:
            payload = b"establishment_id,total_hours_worked\n1,2000\n"
            (Path(srv) / "f.csv").write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            with LocalServer(Path(srv)) as s:
                spec = DatasetFile(
                    key="good",
                    calendar_year=1999,
                    url=f"{s.base}/f.csv",
                    local_name="f.csv",
                    expected_bytes=len(payload),
                    expected_sha256=digest,
                )
                records = download_all(
                    Path(dst), files=[spec], verbose=False
                )
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].sha256, digest)
            self.assertTrue(records[0].digest_matches_catalog)
            self.assertTrue((Path(dst) / "manifest.json").exists())
            self.assertEqual(_sha256_of(Path(dst) / "f.csv"), digest)

    def test_no_partial_file_left_behind_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as srv, tempfile.TemporaryDirectory() as dst:
            with LocalServer(Path(srv)) as s:
                spec = DatasetFile(
                    key="nope",
                    calendar_year=1999,
                    url=f"{s.base}/absent",
                    local_name="absent",
                )
                with self.assertRaises(DownloadError):
                    download_one(spec, Path(dst), verbose=False)
            leftovers = list(Path(dst).iterdir())
            self.assertEqual(leftovers, [], f"stray files: {leftovers}")


if __name__ == "__main__":
    unittest.main()
