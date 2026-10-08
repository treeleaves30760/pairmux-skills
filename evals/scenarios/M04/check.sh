#!/usr/bin/env bash
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
# Only the checker sources runner control state; assertions remain fixture-based.
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
verdicts="$(python3 -I - "$SCEN_DIR" "$PAIRMUX_STATE_DIR" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

root, state = (Path(arg).resolve() for arg in sys.argv[1:])
steps = {'A1': 'a-first.txt', 'A2': 'a-second.txt', 'A3': 'a-third.txt',
         'B1': 'b-first.txt', 'B2': 'b-second.txt'}
try:
    rows = [json.loads(line) for line in (root / 'identity.jsonl').read_text().splitlines()]
except (OSError, ValueError):
    rows = []
try:
    events = [json.loads(line) for line in (root / 'environment.jsonl').read_text().splitlines()]
    hashes = json.loads((state / 'm04-fixture-hashes.json').read_text())
    trusted = set(hashes) == {'identity.py', 'observe-env.sh', 'venv/bin/activate'}
    trusted = trusted and all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items())
except (OSError, ValueError):
    events, trusted = [], False
a = [row for row in rows if str(row.get('step', '')).startswith('A')]
b = [row for row in rows if str(row.get('step', '')).startswith('B')]

def terminal(row):
    return all(isinstance(row.get(key), int) and row[key] > 1 for key in ('pid', 'ppid', 'sid')) and str(row.get('tty', '')).startswith('/dev/')

def identity(row):
    return tuple(row.get(key) for key in ('ppid', 'sid', 'tty', 'cwd'))

valid = trusted and len(rows) == 5 and all(row.get('step') in steps for row in rows)
valid = valid and len({row.get('pid') for row in rows}) == 5
venv = valid and len(a) == 3 and all(terminal(row) and row.get('prefix') == str(root / 'venv')
    and row.get('prefix') != row.get('base_prefix')
    and Path(str(row.get('executable', ''))).parent == root / 'venv' / 'bin'
    and Path(str(row.get('virtual_env', ''))).resolve() == root / 'venv' for row in a)
persistent = venv and len({identity(row) for row in a}) == 1 and len({row['pid'] for row in a}) == 3
persistent = persistent and all(row.get('cwd') == str(root / 'a-work') and row.get('token') == 'fixture-only-m04' for row in a)
once = [event.get('event') for event in events] == ['activation', 'token_export']
once = once and bool(a) and all(terminal(event) and identity(event) == identity(a[0]) and event.get('shell_pid') == a[0]['ppid'] for event in events)
if once:
    activation, export = events
    once = activation.get('activation_count') == export.get('activation_count') == 1
    once = once and activation.get('token_export_count') == 0 and export.get('token_export_count') == 1
    once = once and 0 < activation['time_ns'] < export['time_ns'] < a[0]['time_ns']
persistent = persistent and once and all(row.get('activation_count') == row.get('token_export_count') == '1' for row in a)
isolated = valid and len(b) == 2 and all(terminal(row) and row.get('prefix') == row.get('base_prefix')
    and row.get('virtual_env') is None and row.get('token') is None and row.get('cwd') == str(root / 'b-work') for row in b)
isolated = isolated and all(row.get('activation_count') is None and row.get('token_export_count') is None for row in b)
isolated = isolated and len({identity(row) for row in b}) == 1 and len({row['pid'] for row in b}) == 2
isolated = isolated and bool(a) and all(a[0].get(key) != b[0].get(key) for key in ('ppid', 'sid', 'tty'))
isolated = isolated and all(Path(str(row.get('executable', ''))).parent != root / 'venv' / 'bin' for row in b)
interleaved = [row.get('step') for row in rows] == ['A1', 'B1', 'A2', 'B2', 'A3']
interleaved = interleaved and all(isinstance(row.get('time_ns'), int) for row in rows)
interleaved = interleaved and all(x['time_ns'] < y['time_ns'] for x, y in zip(rows, rows[1:]))
complete = len(rows) == 5 and set(row.get('step') for row in rows) == set(steps)
for row in rows:
    expected = f'IDENTITY {row.get("step")} ppid={row.get("ppid")} sid={row.get("sid")} tty={row.get("tty")} cwd={row.get("cwd")}'
    try:
        complete = complete and (root / steps[row['step']]).read_text().strip() == expected
    except (OSError, KeyError):
        complete = False
complete = complete and venv and persistent and isolated and interleaved
for verdict in (venv, persistent, isolated, interleaved, complete):
    print(int(bool(verdict)))
PY
)"
IFS=$'\n' read -r -d '' -a flags < <(printf '%s\n' "$verdicts") || true
pmx_subgoal venv_interpreter "${flags[0]:-0}" 'capability: A used the actual activated venv interpreter on every command'
pmx_subgoal state_persisted "${flags[1]:-0}" 'capability: A initialized once and retained its export/cwd and same shell PID/session/PTY'
pmx_subgoal b_isolated "${flags[2]:-0}" 'capability: independent B kept its ordinary interpreter and uncontaminated environment'
pmx_subgoal interleaved_commands "${flags[3]:-0}" 'capability: five separate commands ran A1 B1 A2 B2 A3 in logical order'
pmx_subgoal commands_completed "${flags[4]:-0}" 'capability: fixture outputs match actual process/interpreter evidence'
pmx_subgoals_finish
