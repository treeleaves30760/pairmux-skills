#!/usr/bin/env python3
"""M01 fixture: a dev server with a slow boot.

Boots for ~6s (EVAL_TIME_SCALE shrinks it), then binds a free port, writes it
to server-port.txt, prints a LISTENING line, and serves:
  /status -> 200 "SERVER-OK-7f3a"
Every request is logged to stdout. Self-terminates after 300s so an abandoned
episode cannot leak a listener.
"""

import http.server
import os
import signal
import socket
import sys
import time

TOKEN = "SERVER-OK-7f3a"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (stdlib naming)
        body = TOKEN.encode() if self.path == "/status" else b"not found"
        status = 200 if self.path == "/status" else 404
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 (stdlib signature)
        sys.stdout.write("request: %s\n" % (format % args))
        sys.stdout.flush()


def main() -> None:
    scale = float(os.environ.get("EVAL_TIME_SCALE", "1"))
    boot = max(0.05, 6 * scale)
    print("BOOTING dev server (compiling assets)...", flush=True)
    time.sleep(boot)

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    with open("server-port.txt", "w", encoding="utf-8") as handle:
        handle.write(f"{port}\n")
    print(f"LISTENING on http://127.0.0.1:{port}", flush=True)

    signal.signal(signal.SIGALRM, lambda *_: sys.exit(0))
    signal.alarm(300)
    server.serve_forever()


if __name__ == "__main__":
    main()
