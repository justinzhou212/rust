#!/usr/bin/env python3
"""
Local deterministic HTTP payload server.
Serves pre-generated payload files with content-addressed URLs.
Used by fixture 8 (pinned network download) and others.
"""

import hashlib
import http.server
import json
import os
import sys
import threading


DEFAULT_PORT = 8080
PAYLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class PayloadServerHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler for serving deterministic payloads."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PAYLOAD_DIR, **kwargs)

    def log_message(self, format, *args):
        sys.stderr.write(
            f"[payload-server] {self.address_string()} - {format % args}\n"
        )

    def do_GET(self):
        """Handle GET requests, serving payload files."""
        self.log_message("GET %s", self.path)

        # Integrity verification endpoint
        if self.path == "/verify":
            self._serve_integrity_manifest()
            return

        super().do_GET()

    def _serve_integrity_manifest(self):
        """Serve a manifest of all available payloads and their digests."""
        manifest = {}
        if os.path.isdir(PAYLOAD_DIR):
            for name in sorted(os.listdir(PAYLOAD_DIR)):
                path = os.path.join(PAYLOAD_DIR, name)
                if os.path.isfile(path):
                    with open(path, "rb") as f:
                        digest = hashlib.sha256(f.read()).hexdigest()
                    manifest[name] = {
                        "sha256": digest,
                        "size": os.path.getsize(path),
                        "url": f"/{name}",
                    }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(manifest, indent=2).encode())


def start_server(port=DEFAULT_PORT, data_dir=None):
    """Start the payload server."""
    global PAYLOAD_DIR
    if data_dir:
        PAYLOAD_DIR = data_dir

    os.makedirs(PAYLOAD_DIR, exist_ok=True)

    server = http.server.HTTPServer(("0.0.0.0", port), PayloadServerHandler)
    print(f"Payload server listening on port {port}, serving from {PAYLOAD_DIR}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    data_dir = sys.argv[2] if len(sys.argv) > 2 else None
    server = start_server(port, data_dir)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
