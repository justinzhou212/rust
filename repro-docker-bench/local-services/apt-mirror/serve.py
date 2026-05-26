#!/usr/bin/env python3
"""
Local deterministic apt mirror.
Serves pre-cached .deb packages with fixed repository metadata.
Ensures apt installs are reproducible across builds.
"""

import http.server
import os
import sys
import threading


DEFAULT_PORT = 8081
MIRROR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class AptMirrorHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler for apt mirror requests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=MIRROR_DIR, **kwargs)

    def log_message(self, format, *args):
        """Log requests for network monitoring."""
        sys.stderr.write(f"[apt-mirror] {self.address_string()} - {format % args}\n")

    def do_GET(self):
        """Handle GET requests with deterministic responses."""
        # Log the request
        self.log_message("GET %s", self.path)

        # Serve from mirror data directory
        super().do_GET()


def start_mirror(port=DEFAULT_PORT, data_dir=None):
    """Start the apt mirror server."""
    global MIRROR_DIR
    if data_dir:
        MIRROR_DIR = data_dir

    os.makedirs(MIRROR_DIR, exist_ok=True)

    server = http.server.HTTPServer(("0.0.0.0", port), AptMirrorHandler)
    print(f"Apt mirror listening on port {port}, serving from {MIRROR_DIR}")

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
