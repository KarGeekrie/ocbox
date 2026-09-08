#!/usr/bin/env python3
"""Stand-in for `opencode serve`, used only by ocbox's real-Podman integration
test (see ../test_end_to_end.py). Mimics enough of OpenCode's documented
surface - `--hostname`/`--port` flags, HTTP Basic Auth gated by
OPENCODE_SERVER_USERNAME/OPENCODE_SERVER_PASSWORD - to prove ocbox's
sandboxing mechanism against a real container, without depending on network
access to opencode.ai to fetch the real binary.
"""

from __future__ import annotations

import argparse
import base64
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

OK_BODY = b"ocbox-fake-opencode-ok"


def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
    expected_user = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    expected_pass = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    header = handler.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[len("Basic ") :]).decode()
        user, _, password = decoded.partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return user == expected_user and password == expected_pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # untyped args: stdlib signature
        pass

    def _unauthorized(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="opencode"')
        self.end_headers()

    def do_GET(self) -> None:  # non-PEP8 name: stdlib handler method
        if not _check_auth(self):
            self._unauthorized()
            return

        if self.path == "/llm-check":
            llm_port = os.environ["OCBOX_CONTAINER_LLM_PORT"]
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{llm_port}/", timeout=5
                ) as resp:
                    body = resp.read()
            except urllib.error.URLError as exc:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(str(exc).encode())
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.end_headers()
        self.wfile.write(OK_BODY)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hostname", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    server = HTTPServer((args.hostname, args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
