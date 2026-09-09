"""Offline HTTP harness used by CI. Explicit SQLite, real handler, no AWS sockets.

Run from a provisioned CI environment with python tests/http_server.py.
This harness binds loopback and never supplies live coordinator authorization.
"""

from __future__ import annotations

import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


def main() -> None:
    os.environ["MERISMOS_OFFLINE_HTTP"] = "1"
    os.environ.setdefault("MERISMOS_WORKSPACE_DB", "/tmp/merismos-workspace.sqlite")
    os.environ["MERISMOS_LEDGER"] = "memory"
    os.environ["MERISMOS_ROLE"] = "reader"
    os.environ["MERISMOS_MODEL"] = "scripted"
    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
    os.environ.pop("MERISMOS_CORPUS_BUCKET", None)
    from merismos.handler import handler

    real_connect = socket.socket.connect

    def connect(self, address):
        if address[0] not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError("The offline HTTP harness refuses external sockets")
        return real_connect(self, address)

    socket.socket.connect = connect

    class Http(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.respond()

        def do_POST(self):  # noqa: N802
            self.respond()

        def respond(self):
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            if length > 32_000:
                self.send_error(413)
                return
            response = handler({
                "requestContext": {"http": {"path": url.path, "method": self.command}},
                "headers": dict(self.headers), "body": self.rfile.read(length).decode(),
                "queryStringParameters": {k: v[0] for k, v in parse_qs(url.query).items()},
            })
            self.send_response(response["statusCode"])
            for key, value in response.get("headers", {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response["body"].encode())
            print(json.dumps({"method": self.command, "path": url.path,
                              "status": response["statusCode"]}), flush=True)

    ThreadingHTTPServer(("127.0.0.1", 8765), Http).serve_forever()


if __name__ == "__main__":
    main()
