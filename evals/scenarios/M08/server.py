#!/usr/bin/env python3
"""Slow, localhost-only HTTP server; request evidence comes from the real handler."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import time

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_hex(8)
STOP = None


def record(event, **fields):
    row = dict(event=event, pid=os.getpid(), ppid=os.getppid(), sid=os.getsid(0),
               tty=os.ttyname(0), cwd=os.getcwd(), time_ns=time.monotonic_ns(), **fields)
    with (ROOT / 'server-events.jsonl').open('a') as handle:
        handle.write(json.dumps(row) + '\n')


def stop(number, _frame):
    global STOP
    STOP = signal.Signals(number).name


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/status':
            self.send_error(404)
            return
        receipt = secrets.token_hex(8)
        line = f'REQUEST receipt={receipt} method=GET path=/status status=200 server_pid={os.getpid()} port={self.server.server_port}'
        with (ROOT / 'requests.log').open('a') as handle:
            handle.write(line + '\n')
        record('request', line=line, receipt=receipt, path=self.path, status=200,
               user_agent=self.headers.get('User-Agent', ''), client=self.client_address[0])
        print(line, flush=True)
        body = f'STATUS OK token={TOKEN} receipt={receipt}\n'.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


if not (sys.stdin.isatty() and sys.stdout.isatty()):
    raise SystemExit('start this server in a live terminal')
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
(ROOT / 'server.pid').write_text(str(os.getpid()) + '\n')
record('started')
print('BOOTING localhost integration server', flush=True)
server = None
try:
    time.sleep(2 * float(os.environ.get('EVAL_TIME_SCALE', '1')))
    if STOP:
        raise SystemExit('server interrupted before readiness')
    server = HTTPServer(('127.0.0.1', 0), Handler)
    server.timeout = 0.2 * float(os.environ.get('EVAL_TIME_SCALE', '1'))
    (ROOT / 'server-port.txt').write_text(str(server.server_port) + '\n')
    record('ready', port=server.server_port, token=TOKEN)
    print(f'READY http://127.0.0.1:{server.server_port}/status', flush=True)
    while STOP is None:
        server.handle_request()
finally:
    if server:
        server.server_close()
    record('stopped', signal=STOP, port=server.server_port if server else None)
    print('SERVER STOPPED', flush=True)
