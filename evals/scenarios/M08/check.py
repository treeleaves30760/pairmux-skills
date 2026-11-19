#!/usr/bin/env python3
"""M08 check. Fixture evidence only: readiness, curl request, readback, single request, shutdown."""
import json
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

root = evallib.scenario_dir(__file__).resolve()


def text(name):
    try:
        return evallib.read_answer(root / name).strip()
    except (OSError, UnicodeError):
        return ''


try:
    rows = [json.loads(line) for line in (root / 'server-events.jsonl').read_text(encoding="utf-8").splitlines()]
except (OSError, ValueError):
    rows = []


def one(event):
    found = [row for row in rows if row.get('event') == event]
    return found[0] if len(found) == 1 else {}


def stamp(row):
    return row.get('time_ns', 0)


start, ready, stopped = (one(event) for event in ('started', 'ready', 'stopped'))
requests = [row for row in rows if row.get('event') == 'request']
request = requests[0] if len(requests) == 1 else {}
valid = bool(rows) and all(all(isinstance(row.get(key), int) and row[key] > 1 for key in ('pid', 'ppid', 'sid'))
    and str(row.get('tty', '')).startswith(evallib.TTY_PREFIX) and evallib.same_path(row.get('cwd'), root) for row in rows)
valid = valid and len({row.get('pid') for row in rows}) == 1
valid = valid and len({(row.get('ppid'), row.get('sid'), row.get('tty'), row.get('cwd')) for row in rows}) == 1
port = ready.get('port', 0)
started = valid and start.get('pid') == ready.get('pid') and 0 < stamp(start) < stamp(ready)
started = started and isinstance(port, int) and 0 < port < 65536 and text('server-port.txt') == str(port)
started = started and text('server.pid') == str(start.get('pid'))
expected_line = f'REQUEST receipt={request.get("receipt")} method=GET path=/status status=200 server_pid={start.get("pid")} port={port}'
fetched = started and request.get('path') == '/status' and request.get('status') == 200
fetched = fetched and request.get('client') == '127.0.0.1' and str(request.get('user_agent', '')).startswith('curl/')
fetched = fetched and stamp(ready) < stamp(request) and request.get('line') == expected_line
fetched = fetched and text('answer-server.txt') == f'STATUS OK token={ready.get("token")} receipt={request.get("receipt")}'
readback = fetched and text('answer-request.txt') == expected_line and text('requests.log') == expected_line
once = fetched and len(requests) == 1 and len(text('requests.log').splitlines()) == 1
shutdown = started and bool(request) and stopped.get('signal') == 'SIGINT'
shutdown = shutdown and stamp(request) < stamp(stopped) and stopped.get('port') == port
if shutdown:
    # Never os.kill(pid, 0) here: on Windows that would terminate the process.
    if evallib.pid_alive(start['pid']):
        shutdown = False
    with socket.socket() as sock:
        sock.settimeout(0.5)
        try:
            sock.connect(('127.0.0.1', port))
        except OSError:
            pass
        else:
            shutdown = False

ledger = evallib.Subgoals()
ledger.add('server_ready', bool(started), 'capability: the actual terminal server PID reached readiness and bound a localhost port')
ledger.add('curl_verified', bool(fetched), 'capability: a real curl request after readiness returned the matching handler receipt')
ledger.add('request_readback', bool(readback), 'capability: the exact server-produced request line was read back')
ledger.add('single_request', bool(once), 'capability: no duplicate requests or server restarts')
ledger.add('clean_shutdown', bool(shutdown), 'capability: original process trapped Ctrl-C, closed its listener, and exited')
ledger.finish()
