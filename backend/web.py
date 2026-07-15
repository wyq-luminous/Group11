#!/usr/bin/env python3
"""
web.py — Minimal HTTP dashboard server for UNO-Q Remote Control.

Serves:
  GET /api/status      — JSON system status  (sysinfo.get_full_status())
  GET /                 — Dashboard HTML page  (frontend/index.html)

Listens on 0.0.0.0 so the dashboard is accessible from any device
on the same network (or via phone hotspot).

Uses Python stdlib http.server only — no Flask, no extra deps.
"""

import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

# Project root (where frontend/ lives)
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add project dir to path so backend imports work
sys.path.insert(0, PROJECT_DIR)

from backend.sysinfo import get_full_status


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the dashboard."""

    def log_message(self, format, *args):
        """Quiet logging — only show essential info."""
        print(f"[web] {self.client_address[0]} - {format % args}")

    def _send_json(self, data, status=200):
        """Send a JSON response with CORS headers."""
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        """Send an HTML response."""
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code, message):
        """Send a JSON error response."""
        self._send_json({"error": message}, status=code)

    def do_GET(self):
        """Route GET requests."""
        if self.path == "/api/status":
            try:
                status = get_full_status()
                self._send_json(status)
            except Exception as e:
                self._send_error(500, str(e))

        elif self.path == "/" or self.path == "/index.html":
            try:
                index_path = os.path.join(PROJECT_DIR, "frontend", "index.html")
                with open(index_path, "r") as f:
                    html = f.read()
                self._send_html(html)
            except FileNotFoundError:
                self._send_error(404, "Dashboard page not found")
            except Exception as e:
                self._send_error(500, str(e))

        else:
            self._send_error(404, f"Not found: {self.path}")

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="UNO-Q Dashboard Server")
    parser.add_argument("--port", type=int, default=8080, help="Listen port (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Listen host (default: 0.0.0.0)")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), DashboardHandler)
    print(f"[web] UNO-Q Dashboard listening on http://{args.host}:{args.port}")
    print(f"[web] API endpoint: http://{args.host}:{args.port}/api/status")
    print(f"[web] Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[web] Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
