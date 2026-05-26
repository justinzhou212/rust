#!/usr/bin/env python3
"""
Local deterministic PyPI mirror.
Serves pre-built wheels with fixed metadata for reproducible pip installs.
"""

import http.server
import os
import sys
import threading


DEFAULT_PORT = 8082
MIRROR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class PyPIMirrorHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler for PyPI mirror requests (PEP 503 simple API)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=MIRROR_DIR, **kwargs)

    def log_message(self, format, *args):
        sys.stderr.write(f"[pypi-mirror] {self.address_string()} - {format % args}\n")

    def do_GET(self):
        """Handle GET requests with PEP 503 simple API responses."""
        self.log_message("GET %s", self.path)

        # Handle simple API index
        if self.path == "/simple/" or self.path == "/simple":
            self._serve_index()
            return

        # Handle package page
        if self.path.startswith("/simple/"):
            parts = self.path.rstrip("/").split("/")
            if len(parts) == 3:
                self._serve_package_page(parts[2])
                return

        # Serve files directly
        super().do_GET()

    def _serve_index(self):
        """Serve the simple API index page."""
        packages = []
        simple_dir = os.path.join(MIRROR_DIR, "simple")
        if os.path.isdir(simple_dir):
            packages = sorted(os.listdir(simple_dir))

        html = "<!DOCTYPE html><html><body>\n"
        for pkg in packages:
            html += f'<a href="/simple/{pkg}/">{pkg}</a>\n'
        html += "</body></html>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def _serve_package_page(self, package_name):
        """Serve a package's available files."""
        pkg_dir = os.path.join(MIRROR_DIR, "simple", package_name)
        if not os.path.isdir(pkg_dir):
            self.send_error(404)
            return

        files = sorted(os.listdir(pkg_dir))
        html = f"<!DOCTYPE html><html><body><h1>{package_name}</h1>\n"
        for f in files:
            html += f'<a href="/packages/{package_name}/{f}">{f}</a>\n'
        html += "</body></html>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())


def start_mirror(port=DEFAULT_PORT, data_dir=None):
    """Start the PyPI mirror server."""
    global MIRROR_DIR
    if data_dir:
        MIRROR_DIR = data_dir

    os.makedirs(MIRROR_DIR, exist_ok=True)
    os.makedirs(os.path.join(MIRROR_DIR, "simple"), exist_ok=True)

    server = http.server.HTTPServer(("0.0.0.0", port), PyPIMirrorHandler)
    print(f"PyPI mirror listening on port {port}, serving from {MIRROR_DIR}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = start_mirror(port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
