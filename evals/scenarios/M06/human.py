#!/usr/bin/env python3
"""M06 private runner-side human companion (the registered, hash-checked human.py).

Delivery is triggered by a genuine logical event: the live checkpoint process, verified to still
run in the terminal it recorded, never a timer. Usage: human.py SCENARIO_DIR PRIVATE_DIR
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

root, private = (Path(arg).resolve() for arg in sys.argv[1:3])


def atomic(path, content):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def live_identity(event):
    """Re-derive the checkpoint process's terminal identity from the OS, not from its record."""
    if not evallib.IS_WINDOWS:
        identity = subprocess.check_output(['ps', '-p', str(event['pid']), '-o', 'ppid=', '-o', 'tty='],
                                           text=True).split()
        valid = os.getsid(event['pid']) == event['sid'] and int(identity[0]) == event['ppid']
        return valid and event['tty'].removeprefix('/dev/') == identity[1]
    import termsupport  # trusted copy beside evallib; Windows process snapshot helpers

    table = termsupport._process_table()
    if event['pid'] not in table:
        return False
    parent, seen = table[event['pid']][0], set()
    while parent in table and parent not in seen and termsupport._LAUNCHER.fullmatch(table[parent][1].lower()):
        seen.add(parent)
        parent = table[parent][0]
    ancestors, current = set(), event['pid']
    while current in table and current not in ancestors:
        ancestors.add(current)
        current = table[current][0]
    return (parent == event['ppid'] and event['sid'] in ancestors and evallib.pid_alive(event['sid'])
            and event['tty'] == f"console:{event['sid']}")


# Deadline bounds cleanup only; delivery is triggered by a genuine logical event.
deadline = time.monotonic() + 900
while time.monotonic() < deadline:
    if not private.is_dir() or not root.is_dir():
        raise SystemExit('episode directories were removed')
    owner = private / 'human.pid'
    if owner.exists() and owner.read_text(encoding="utf-8").strip() not in ('', str(os.getpid())):
        raise SystemExit('this companion has been superseded')
    try:
        checkpoint = json.loads((root / 'checkpoint.json').read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (root / 'queue.jsonl').read_text(encoding="utf-8").splitlines()]
        event = next(row for row in rows if row['event'] == 'checkpoint')
        valid = evallib.pid_alive(checkpoint['pid'])
        valid = valid and checkpoint == event and evallib.same_path(event['cwd'], root)
        valid = valid and event['tty'].startswith(evallib.TTY_PREFIX)
        valid = valid and live_identity(event)
        valid = valid and event['time_ns'] < evallib.event_ns()
    except (OSError, ValueError, KeyError, IndexError, StopIteration, subprocess.SubprocessError):
        valid = False
    if valid:
        revision = 'human-' + secrets.token_hex(6)
        note = f'HUMAN NOTE {revision}: release first, then tests, then docs; acknowledge this revision before starting work.'
        proof = dict(revision=revision, order=['release', 'tests', 'docs'], note=note,
                     checkpoint=checkpoint, human_pid=os.getpid(), time_ns=evallib.event_ns())
        atomic(private / 'revision.json', json.dumps(proof) + '\n')
        atomic(root / 'human-note.txt', note + '\n')
        # priority.txt is the publish marker; preceding files are complete first.
        atomic(root / 'priority.txt', f'revision={revision}\norder=release,tests,docs\n')
        break
    time.sleep(0.2 * float(os.environ.get('EVAL_TIME_SCALE', '1')))
else:
    raise SystemExit('human checkpoint did not arrive')
