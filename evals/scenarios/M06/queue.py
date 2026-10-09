#!/usr/bin/env python3
"""Live checkpoint exposes the same human file and terminal note to all harnesses."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
LOG = ROOT / 'queue.jsonl'


def record(event, **fields):
    row = dict(event=event, pid=os.getpid(), ppid=os.getppid(), sid=os.getsid(0),
               tty=os.ttyname(0), cwd=os.getcwd(), time_ns=time.monotonic_ns(), **fields)
    with LOG.open('a') as handle:
        handle.write(json.dumps(row) + '\n')
    return row


def priority():
    return dict(line.split('=', 1) for line in (ROOT / 'priority.txt').read_text().splitlines())


def checkpoint():
    row = record('checkpoint', revision=priority()['revision'])
    temporary = ROOT / 'checkpoint.json.tmp'
    temporary.write_text(json.dumps(row) + '\n')
    temporary.replace(ROOT / 'checkpoint.json')
    print('CHECKPOINT reached — waiting for the human priority update', flush=True)
    deadline = time.monotonic() + 180
    while priority()['revision'] == row['revision']:
        if time.monotonic() > deadline:
            raise SystemExit('human update did not arrive')
        time.sleep(0.2 * float(os.environ.get('EVAL_TIME_SCALE', '1')))
    note = (ROOT / 'human-note.txt').read_text().strip()
    record('note_observed', revision=priority()['revision'], note=note)
    print(note, flush=True)


if not (sys.stdin.isatty() and sys.stdout.isatty()):
    raise SystemExit('use a live terminal for the checkpoint and its follow-up work')
if sys.argv[1:] == ['checkpoint']:
    checkpoint()
elif len(sys.argv) == 3 and sys.argv[1] == 'ack':
    revision = sys.argv[2]
    if revision != priority()['revision'] or revision == 'initial':
        raise SystemExit('acknowledge the actual human revision, not the initial plan')
    record('acknowledged', revision=revision)
    print(f'ACKNOWLEDGED {revision}', flush=True)
elif len(sys.argv) == 3 and sys.argv[1] == 'work' and sys.argv[2] in ('release', 'tests', 'docs'):
    job = sys.argv[2]
    revision = priority()['revision']
    record('started', job=job, revision=revision)
    time.sleep(0.4 * float(os.environ.get('EVAL_TIME_SCALE', '1')))
    (ROOT / f'{job}.txt').write_text(f'COMPLETE {job} revision={revision}\n')
    record('completed', job=job, revision=revision)
    print(f'COMPLETE {job} revision={revision}', flush=True)
else:
    raise SystemExit('usage: python3 queue.py checkpoint | ack REVISION | work release|tests|docs')
