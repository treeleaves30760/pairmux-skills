#!/usr/bin/env bash
# Private runner-side human companion (the registered, hash-checked human.sh).
set -euo pipefail
exec python3 -I - "$1" "$2" <<'PY'
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import sys

root, private = (Path(arg).resolve() for arg in sys.argv[1:])

def atomic(path, content):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(content)
    temporary.replace(path)

# Deadline bounds cleanup only; delivery is triggered by a genuine logical event.
deadline = time.monotonic() + 900
while time.monotonic() < deadline:
    if not private.is_dir() or not root.is_dir():
        raise SystemExit('episode directories were removed')
    owner = private / 'human.pid'
    if owner.exists() and owner.read_text().strip() not in ('', str(os.getpid())):
        raise SystemExit('this companion has been superseded')
    try:
        checkpoint = json.loads((root / 'checkpoint.json').read_text())
        rows = [json.loads(line) for line in (root / 'queue.jsonl').read_text().splitlines()]
        event = next(row for row in rows if row['event'] == 'checkpoint')
        os.kill(checkpoint['pid'], 0)
        identity = subprocess.check_output(['ps', '-p', str(event['pid']), '-o', 'ppid=', '-o', 'tty='], text=True).split()
        valid = checkpoint == event and event['cwd'] == str(root) and event['tty'].startswith('/dev/')
        valid = valid and os.getsid(event['pid']) == event['sid'] and int(identity[0]) == event['ppid']
        valid = valid and event['tty'].removeprefix('/dev/') == identity[1]
        valid = valid and event['time_ns'] < time.monotonic_ns()
    except (OSError, ValueError, KeyError, IndexError, StopIteration, subprocess.SubprocessError):
        valid = False
    if valid:
        revision = 'human-' + secrets.token_hex(6)
        note = f'HUMAN NOTE {revision}: release first, then tests, then docs; acknowledge this revision before starting work.'
        proof = dict(revision=revision, order=['release', 'tests', 'docs'], note=note,
                     checkpoint=checkpoint, human_pid=os.getpid(), time_ns=time.monotonic_ns())
        atomic(private / 'revision.json', json.dumps(proof) + '\n')
        atomic(root / 'human-note.txt', note + '\n')
        # priority.txt is the publish marker; preceding files are complete first.
        atomic(root / 'priority.txt', f'revision={revision}\norder=release,tests,docs\n')
        break
    time.sleep(0.2 * float(os.environ.get('EVAL_TIME_SCALE', '1')))
else:
    raise SystemExit('human checkpoint did not arrive')
PY
