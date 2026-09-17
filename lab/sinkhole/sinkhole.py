"""Lab egress sinkhole.

The only destination any corpus server is permitted to reach. A5 (argument
exfiltration) is defined by the *attempt* to transmit, not by its success, so
the lab needs somewhere that records attempts without anything leaving.

Egress is blocked at the network layer regardless; this exists so the runner can
observe that an exfiltration attempt happened, and so the A5 server has a
plausible destination to construct at call time.

Stdlib only, so the container has no dependencies.

  POST /collect   record an attempt, return 204
  GET  /captures  return everything recorded, as JSON
  POST /reset     clear the log, return 204
  GET  /health    liveness
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_CAPTURES = 1000
MAX_BODY = 64 * 1024

_lock = threading.Lock()
_captures: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    server_version = "mcpbench-sinkhole/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"[sinkhole] {fmt % args}\n")

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _empty(self, code: int = 204) -> None:
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.startswith("/captures"):
            with _lock:
                self._json(200, {"count": len(_captures), "captures": list(_captures)})
        elif self.path.startswith("/health"):
            self._json(200, {"status": "ok", "service": "sinkhole"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path.startswith("/reset"):
            with _lock:
                _captures.clear()
            self._empty()
            return

        if not self.path.startswith("/collect"):
            self._json(404, {"error": "not found"})
            return

        length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None

        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "path": self.path,
            "source": self.client_address[0],
            "headers": {k.lower(): v for k, v in self.headers.items()
                        if k.lower() in ("user-agent", "content-type", "x-source-server")},
            "body_raw": raw[:4096],
            "body_json": parsed,
        }
        with _lock:
            _captures.append(record)
            del _captures[:-MAX_CAPTURES]

        sys.stderr.write(
            f"[sinkhole] CAPTURED from {record['source']}: {raw[:200]}\n")
        self._empty()


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer that does not perform a reverse DNS lookup on bind.

    http.server.HTTPServer.server_bind calls socket.getfqdn(), which blocks for
    a long time when DNS is unreachable. The lab blocks egress by design, so DNS
    is unreachable by design, and the stock implementation hangs before it ever
    listens. Any server added to this lab needs the same treatment.
    """

    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def main() -> None:
    port = int(os.environ.get("PORT", 8900))
    server = Server(("0.0.0.0", port), Handler)
    sys.stderr.write(f"[sinkhole] listening on 0.0.0.0:{port}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
