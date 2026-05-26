#!/usr/bin/env python3
"""
Local deterministic npm registry.
Serves pre-cached packages with fixed metadata for reproducible npm installs.
Implements a minimal subset of the npm registry API.
"""

import http.server
import json
import os
import sys
import threading


DEFAULT_PORT = 8083
REGISTRY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class NpmRegistryHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for npm registry API requests."""

    def log_message(self, format, *args):
        sys.stderr.write(f"[npm-registry] {self.address_string()} - {format % args}\n")

    def do_GET(self):
        """Handle GET requests for package metadata and tarballs."""
        self.log_message("GET %s", self.path)

        # Package metadata: /<package-name>
        if self.path.startswith("/-/") or self.path.startswith("/@"):
            self._serve_package_metadata()
            return

        parts = self.path.strip("/").split("/")
        if len(parts) == 1 and parts[0]:
            self._serve_package_metadata(parts[0])
            return

        # Tarball: /<package>/-/<tarball>
        if len(parts) >= 3 and parts[1] == "-":
            self._serve_tarball(parts[0], parts[2])
            return

        # Root
        if self.path == "/" or self.path == "":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"db_name": "repro-bench-registry"}).encode())
            return

        self.send_error(404)

    def _serve_package_metadata(self, package_name=None):
        """Serve npm package metadata JSON."""
        if not package_name:
            package_name = self.path.strip("/")

        meta_path = os.path.join(
            REGISTRY_DIR, "packages", package_name, "metadata.json"
        )
        if os.path.isfile(meta_path):
            with open(meta_path) as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data.encode())
        else:
            self.send_error(404, f"Package not found: {package_name}")

    def _serve_tarball(self, package_name, tarball_name):
        """Serve package tarball."""
        tarball_path = os.path.join(
            REGISTRY_DIR, "packages", package_name, tarball_name
        )
        if os.path.isfile(tarball_path):
            with open(tarball_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404, f"Tarball not found: {tarball_name}")


def start_registry(port=DEFAULT_PORT, data_dir=None):
    """Start the npm registry server."""
    global REGISTRY_DIR
    if data_dir:
        REGISTRY_DIR = data_dir

    os.makedirs(os.path.join(REGISTRY_DIR, "packages"), exist_ok=True)

    server = http.server.HTTPServer(("0.0.0.0", port), NpmRegistryHandler)
    print(f"npm registry listening on port {port}, serving from {REGISTRY_DIR}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = start_registry(port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
