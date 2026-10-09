#!/usr/bin/env bash
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
verdicts="$(python3 -I - "$SCEN_DIR" <<'PY'
import json
import os
from pathlib import Path
import socket
import sys

root = Path(sys.argv[1]).resolve()
def text(name):
    try:
        return (root / name).read_text().strip()
    except OSError:
        return ''
try:
    rows = [json.loads(line) for line in (root / 'server-events.jsonl').read_text().splitlines()]
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
    and str(row.get('tty', '')).startswith('/dev/') and row.get('cwd') == str(root) for row in rows)
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
    try:
        os.kill(start['pid'], 0)
    except ProcessLookupError:
        pass
    else:
        shutdown = False
    with socket.socket() as sock:
        sock.settimeout(0.5)
        try:
            sock.connect(('127.0.0.1', port))
        except OSError:
            pass
        else:
            shutdown = False
for verdict in (started, fetched, readback, once, shutdown):
    print(int(bool(verdict)))
PY
)"
IFS=$'\n' read -r -d '' -a flags < <(printf '%s\n' "$verdicts") || true
pmx_subgoal server_ready "${flags[0]:-0}" 'capability: the actual terminal server PID reached readiness and bound a localhost port'
pmx_subgoal curl_verified "${flags[1]:-0}" 'capability: a real curl request after readiness returned the matching handler receipt'
pmx_subgoal request_readback "${flags[2]:-0}" 'capability: the exact server-produced request line was read back'
pmx_subgoal single_request "${flags[3]:-0}" 'capability: no duplicate requests or server restarts'
pmx_subgoal clean_shutdown "${flags[4]:-0}" 'capability: original process trapped Ctrl-C, closed its listener, and exited'
pmx_subgoals_finish
