"""Serve the static paper-trading site locally over HTTP.

Opening the HTML files with ``file://`` prevents browsers from loading the
audit snapshot with ``fetch``.  This tiny loopback-only server keeps the
production GitHub Pages layout unchanged while making the local site usable.
"""

from __future__ import annotations

import argparse
import functools
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"
LOCAL_HOST = "127.0.0.1"


class NoCacheRequestHandler(SimpleHTTPRequestHandler):
    """Serve mutable dashboard assets without retaining stale browser copies."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def create_server(*, port: int = 8765, open_browser: bool = False) -> ThreadingHTTPServer:
    """Create a loopback HTTP server rooted at the project's docs directory."""
    handler = functools.partial(NoCacheRequestHandler, directory=str(DOCS_ROOT))
    server = ThreadingHTTPServer((LOCAL_HOST, port), handler)
    if open_browser:
        host, bound_port = server.server_address
        webbrowser.open(f"http://{host}:{bound_port}/paper-trading/")
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the local paper-trading dashboard.")
    parser.add_argument("--port", type=int, default=8765, help="Loopback port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    args = parser.parse_args()
    server = create_server(port=args.port, open_browser=not args.no_browser)
    host, bound_port = server.server_address
    print(f"Paper trading dashboard: http://{host}:{bound_port}/paper-trading/")
    print("Press Ctrl+C to stop the local server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
