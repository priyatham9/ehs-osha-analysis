"""Standard-library static server and CLI shared by standalone browser checks."""

import argparse
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
from threading import Thread


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@contextmanager
def browser_target(page_name, legacy_url_env=None):
    """Serve this checkout on an isolated loopback port unless a URL is supplied."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", default=os.environ.get("BASE_URL"),
        help="Existing docs root URL; otherwise start an isolated local server.",
    )
    parser.add_argument(
        "--artifacts", type=Path, default=os.environ.get("AUDIT_ARTIFACTS"),
        help="Screenshots and downloads directory (default: a new temporary directory).",
    )
    args = parser.parse_args()
    output = args.artifacts or Path(tempfile.mkdtemp(prefix="browser-audit-"))
    output.mkdir(parents=True, exist_ok=True)
    print(f"Browser artifacts: {output.resolve()}", flush=True)
    legacy_url = os.environ.get(legacy_url_env) if legacy_url_env else None
    if args.base_url or legacy_url:
        url = f"{args.base_url.rstrip('/')}/{page_name}" if args.base_url else legacy_url
        yield url, output
        return
    docs = Path(__file__).resolve().parents[1] / "docs"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(docs)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/{page_name}", output
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
