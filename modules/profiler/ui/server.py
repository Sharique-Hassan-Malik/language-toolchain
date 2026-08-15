"""
Minimal HTTP server that serves the generated flame graph.

Endpoints:
    GET /              → renders flamegraph.html (from file or live data)
    GET /data.json     → the raw flame tree JSON
    GET /profile.json  → the raw sample data JSON

The server is intentionally simple — a single-file stdlib HTTPServer,
no external dependencies.
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class FlameServer:
    """
    Serves a flame graph HTML file over HTTP and optionally opens the browser.

    Usage:
        server = FlameServer(html_path="flamegraph.html", port=8080)
        server.serve(open_browser=True, timeout=None)
    """

    def __init__(
        self,
        html_path:    str = "flamegraph.html",
        json_path:    str | None = None,
        profile_path: str | None = None,
        port:         int = 8080,
    ):
        self.html_path    = html_path
        self.json_path    = json_path
        self.profile_path = profile_path
        self.port         = port

    def serve(self, open_browser: bool = True, timeout: float | None = None):
        """
        Start the HTTP server.

        If timeout is not None the server shuts down after that many seconds.
        Otherwise it runs until Ctrl-C.
        """
        html_path    = self.html_path
        json_path    = self.json_path
        profile_path = self.profile_path
        port         = self.port

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass   # suppress default access log

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self._serve_file(html_path, "text/html")
                elif self.path == "/data.json" and json_path:
                    self._serve_file(json_path, "application/json")
                elif self.path == "/profile.json" and profile_path:
                    self._serve_file(profile_path, "application/json")
                else:
                    self.send_response(404)
                    self.end_headers()

            def _serve_file(self, path: str, content_type: str):
                try:
                    content = Path(path).read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", len(content))
                    self.end_headers()
                    self.wfile.write(content)
                except FileNotFoundError:
                    self.send_response(404)
                    self.end_headers()

        httpd = HTTPServer(("127.0.0.1", port), Handler)
        url   = f"http://127.0.0.1:{port}/"

        print(f"Serving flame graph at {url}")
        print("Press Ctrl-C to stop.\n")

        if open_browser:
            threading.Timer(0.3, lambda: webbrowser.open(url)).start()

        if timeout is not None:
            threading.Timer(timeout, httpd.shutdown).start()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
