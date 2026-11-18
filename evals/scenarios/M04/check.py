#!/usr/bin/env python3
"""M04 check. Only the checker reads runner control state; assertions remain fixture-based."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
env = evallib.load_env(scen_dir=SCEN_DIR)
root, state = SCEN_DIR.resolve(), Path(env.get("PAIRMUX_STATE_DIR", "")).resolve()
WINDOWS = evallib.IS_WINDOWS
VENV_BIN = 'Scripts' if WINDOWS else 'bin'
FIXTURES = ({'identity.py', 'observe-env.ps1', 'venv/Scripts/Activate.ps1'} if WINDOWS
            else {'identity.py', 'observe-env.sh', 'venv/bin/activate'})
steps = {'A1': 'a-first.txt', 'A2': 'a-second.txt', 'A3': 'a-third.txt',
         'B1': 'b-first.txt', 'B2': 'b-second.txt'}
try:
    rows = [json.loads(line) for line in (root / 'identity.jsonl').read_text().splitlines()]
except (OSError, ValueError):
    rows = []
try:
    events = [json.loads(line) for line in (root / 'environment.jsonl').read_text().splitlines()]
    hashes = json.loads((state / 'm04-fixture-hashes.json').read_text())
    trusted = set(hashes) == FIXTURES
    trusted = trusted and all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items())
except (OSError, ValueError):
    events, trusted = [], False
a = [row for row in rows if str(row.get('step', '')).startswith('A')]
b = [row for row in rows if str(row.get('step', '')).startswith('B')]


def terminal(row):
    return all(isinstance(row.get(key), int) and row[key] > 1 for key in ('pid', 'ppid', 'sid')) and str(row.get('tty', '')).startswith(evallib.TTY_PREFIX)


def identity(row):
    return tuple(row.get(key) for key in ('ppid', 'sid', 'tty', 'cwd'))


def venv_path(value):
    try:
        return Path(str(value)).resolve() == root / 'venv'
    except (OSError, ValueError):
        return False


valid = trusted and len(rows) == 5 and all(row.get('step') in steps for row in rows)
valid = valid and len({row.get('pid') for row in rows}) == 5
venv = valid and len(a) == 3 and all(terminal(row) and evallib.same_path(row.get('prefix'), root / 'venv')
    and row.get('prefix') != row.get('base_prefix')
    and (Path(str(row.get('executable', ''))).parent == root / 'venv' / VENV_BIN
         or WINDOWS and evallib.same_path(str(Path(str(row.get('executable', ''))).parent), root / 'venv' / VENV_BIN))
    and venv_path(row.get('virtual_env')) for row in a)
persistent = venv and len({identity(row) for row in a}) == 1 and len({row['pid'] for row in a}) == 3
persistent = persistent and all(evallib.same_path(row.get('cwd'), root / 'a-work') and row.get('token') == 'fixture-only-m04' for row in a)
once = [event.get('event') for event in events] == ['activation', 'token_export']
once = once and bool(a) and all(terminal(event) and identity(event) == identity(a[0]) and event.get('shell_pid') == a[0]['ppid'] for event in events)
if once:
    activation, export = events
    once = activation.get('activation_count') == export.get('activation_count') == 1
    once = once and activation.get('token_export_count') == 0 and export.get('token_export_count') == 1
    once = once and 0 < activation['time_ns'] < export['time_ns'] < a[0]['time_ns']
persistent = persistent and once and all(row.get('activation_count') == row.get('token_export_count') == '1' for row in a)
isolated = valid and len(b) == 2 and all(terminal(row) and row.get('prefix') == row.get('base_prefix')
    and row.get('virtual_env') is None and row.get('token') is None and evallib.same_path(row.get('cwd'), root / 'b-work') for row in b)
isolated = isolated and all(row.get('activation_count') is None and row.get('token_export_count') is None for row in b)
isolated = isolated and len({identity(row) for row in b}) == 1 and len({row['pid'] for row in b}) == 2
isolated = isolated and bool(a) and all(a[0].get(key) != b[0].get(key) for key in ('ppid', 'sid', 'tty'))
isolated = isolated and all(Path(str(row.get('executable', ''))).parent != root / 'venv' / VENV_BIN
                            and not (WINDOWS and evallib.same_path(str(Path(str(row.get('executable', ''))).parent), root / 'venv' / VENV_BIN))
                            for row in b)
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

ledger = evallib.Subgoals()
ledger.add('venv_interpreter', bool(venv), 'capability: A used the actual activated venv interpreter on every command')
ledger.add('state_persisted', bool(persistent), 'capability: A initialized once and retained its export/cwd and same shell PID/session/PTY')
ledger.add('b_isolated', bool(isolated), 'capability: independent B kept its ordinary interpreter and uncontaminated environment')
ledger.add('interleaved_commands', bool(interleaved), 'capability: five separate commands ran A1 B1 A2 B2 A3 in logical order')
ledger.add('commands_completed', bool(complete), 'capability: fixture outputs match actual process/interpreter evidence')
ledger.finish()
