#!/usr/bin/env python3
"""M01: slow boot + loopback-listener approval, interleaved with 42 tests.

The suite pauses halfway until a real /status request. This logical checkpoint,
not elapsed seconds, makes work before AND after readiness observable. The
listener approval is non-secret and must be answered at a live terminal.
"""

import fcntl
import hashlib
import heapq
import http.server
import json
import os
from pathlib import Path
import signal
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
EVENTS = ROOT / "m01-events.jsonl"
TOKEN = "SERVER-OK-7f3a"
FATAL = "2026-08-01T03:14:07Z FATAL: disk quota exceeded on shard-17 token=FT-55d1"


def events():
    if not EVENTS.exists():
        return []
    with EVENTS.open(encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        return [json.loads(line) for line in handle]


def record(event, **fields):
    with EVENTS.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        previous = [json.loads(line) for line in handle]
        entry = {"seq": len(previous) + 1, "event": event, "pid": os.getpid(),
                 "at_ns": time.time_ns(), **fields}
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
        handle.flush()


def until(predicate):
    deadline = time.monotonic() + 280
    while time.monotonic() < deadline:
        if predicate(events()):
            return
        time.sleep(0.05)  # fixture coordination only; never a scoring deadline
    raise TimeoutError("M01 logical checkpoint was not reached")


def step(seconds):
    return max(0.01, seconds * float(os.environ.get("EVAL_TIME_SCALE", "1")))


def suite():
    instance = uuid.uuid4().hex
    record("suite_started", instance=instance, fatal_present=(ROOT / "answer-fatal.txt").exists())
    print("suite checkpoint: waiting for concurrent server boot", flush=True)
    until(lambda entries: any(e["event"] == "server_started" for e in entries))
    case = 0
    for batch in range(1, 19):
        results = []
        # Six batches of three checks, then twelve of two: exactly 42 tests.
        for _ in range(3 if batch <= 6 else 2):
            case += 1
            values = [(case * 37 + i * 13) % 257 for i in range(512)]
            ordered = sorted(values)
            assert heapq.nsmallest(len(values), values) == ordered
            results.append(ordered)
        time.sleep(step(1))
        digest = hashlib.sha256(json.dumps(results).encode()).hexdigest()
        record("suite_batch", instance=instance, unit=batch, digest=digest)
        print(f"test batch {batch}/18 ok", flush=True)
        if batch == 9:
            print("suite checkpoint: waiting for the approved server's /status request", flush=True)
            until(lambda entries: any(e["event"] == "status_requested" for e in entries))
            record("suite_resumed", instance=instance)
    report = "TESTS PASSED 42/42 token=TP-9c2e\n"
    (ROOT / "test-report.txt").write_text(report, encoding="utf-8")
    record("suite_completed", instance=instance, cases=case)
    print(report, end="", flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (stdlib naming)
        body = TOKEN.encode() if self.path == "/status" else b"not found"
        status = 200 if self.path == "/status" else 404
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        if status == 200:
            record("status_requested", instance=self.server.instance,
                   port=self.server.server_port, body=TOKEN)

    def log_message(self, format, *args):  # noqa: A002 (stdlib signature)
        print("request: %s" % (format % args), flush=True)


def serve():
    instance = uuid.uuid4().hex
    server = None
    reason = "error"

    def interrupt(signum, _frame):
        nonlocal reason
        reason = "signal" if signum != signal.SIGALRM else "watchdog"
        raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, interrupt)
    signal.alarm(300)
    record("server_started", instance=instance, fatal_present=(ROOT / "answer-fatal.txt").exists())
    try:
        print("BOOTING dev server (compiling assets)...", flush=True)
        time.sleep(step(6))
        print("boot checkpoint: waiting for the test suite's first completed batch", flush=True)
        until(lambda entries: any(e["event"] == "suite_batch" for e in entries))
        # Reading /dev/tty prevents a pre-filled stdin pipe from substituting
        # for the task's live approval, without making the answer a secret.
        with open("/dev/tty", "r", encoding="utf-8") as tty, open("/dev/tty", "w", encoding="utf-8") as output:
            record("listener_prompt", instance=instance, tty=os.ttyname(tty.fileno()))
            output.write("Enable loopback status endpoint after reviewing FATAL? [y/N] ")
            output.flush()
            answer = tty.readline().strip().lower()
        if answer not in {"y", "yes"}:
            raise RuntimeError("listener not approved")
        fatal = (ROOT / "answer-fatal.txt").read_text(encoding="utf-8")
        if fatal != FATAL + "\n":
            raise RuntimeError("review the exact FATAL line before enabling the listener")
        record("fatal_reviewed", instance=instance,
               digest=hashlib.sha256(fatal.encode()).hexdigest())
        record("listener_approved", instance=instance)
        # HTTPServer binds port 0 itself: no probe-close-rebind port race.
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        server.instance = instance
        (ROOT / "server-port.txt").write_text(f"{server.server_port}\n", encoding="utf-8")
        record("server_ready", instance=instance, port=server.server_port)
        print(f"LISTENING on http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.server_close()
        record("server_stopped", instance=instance, reason=reason)
        signal.alarm(0)


if __name__ == "__main__":
    if sys.argv[1:] == ["--suite"]:
        suite()
    elif not sys.argv[1:]:
        serve()
    else:
        raise SystemExit("usage: bigserver.py [--suite]")
