#!/usr/bin/env python3
"""Record the actual interpreter, environment and persistent terminal identity."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
STEPS = {'A1': 'a-first.txt', 'A2': 'a-second.txt', 'A3': 'a-third.txt',
         'B1': 'b-first.txt', 'B2': 'b-second.txt'}
if len(sys.argv) == 5 and sys.argv[1] in ('activation', 'token_export'):
    row = dict(event=sys.argv[1], shell_pid=int(sys.argv[2]), activation_count=int(sys.argv[3]),
               token_export_count=int(sys.argv[4]), pid=os.getpid(), ppid=os.getppid(),
               sid=os.getsid(0), tty=os.ttyname(0) if sys.stdin.isatty() else None,
               cwd=os.getcwd(), time_ns=time.monotonic_ns())
    with (ROOT / 'environment.jsonl').open('a') as handle:
        handle.write(json.dumps(row) + '\n')
    raise SystemExit(0)
if len(sys.argv) != 2 or sys.argv[1] not in STEPS:
    raise SystemExit('usage: python ../identity.py A1|A2|A3|B1|B2')
step = sys.argv[1]
row = dict(step=step, pid=os.getpid(), ppid=os.getppid(), sid=os.getsid(0),
           tty=os.ttyname(0) if sys.stdin.isatty() else None, cwd=os.getcwd(),
           executable=sys.executable, prefix=sys.prefix, base_prefix=sys.base_prefix,
           virtual_env=os.environ.get('VIRTUAL_ENV'), token=os.environ.get('TOKEN'),
           activation_count=os.environ.get('M04_ACTIVATION_COUNT'),
           token_export_count=os.environ.get('M04_TOKEN_EXPORT_COUNT'),
           time_ns=time.monotonic_ns())
# Log before validation, so a wrong interpreter or contaminated B is observable.
with (ROOT / 'identity.jsonl').open('a') as handle:
    handle.write(json.dumps(row) + '\n')
is_a = step.startswith('A')
expected_cwd = ROOT / ('a-work' if is_a else 'b-work')
valid = row['tty'] and Path(row['cwd']) == expected_cwd
if is_a:
    valid = valid and Path(sys.prefix) == ROOT / 'venv' and sys.prefix != sys.base_prefix
    valid = valid and Path(row['virtual_env'] or '').resolve() == ROOT / 'venv' and row['token'] == 'fixture-only-m04'
else:
    valid = valid and sys.prefix == sys.base_prefix and row['virtual_env'] is None and row['token'] is None
if not valid:
    raise SystemExit('wrong terminal working directory, interpreter, or environment')
line = f'IDENTITY {step} ppid={row["ppid"]} sid={row["sid"]} tty={row["tty"]} cwd={row["cwd"]}'
(ROOT / STEPS[step]).write_text(line + '\n')
print(line, flush=True)
