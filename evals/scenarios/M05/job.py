#!/usr/bin/env python3
"""Three logically overlapping jobs; SIGINT must recover the same live shell."""
import json
import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parent
LOG = ROOT / 'jobs.jsonl'
JOB = sys.argv[1] if len(sys.argv) == 2 else ''
if JOB not in ('alpha', 'beta', 'hang', 'recover') or not sys.stdin.isatty():
    raise SystemExit('usage (in a live terminal): python3 job.py alpha|beta|hang|recover')


def record(event, **fields):
    row = dict(event=event, job=JOB, pid=os.getpid(), ppid=os.getppid(), sid=os.getsid(0),
               tty=os.ttyname(0), cwd=os.getcwd(), time_ns=time.monotonic_ns(), **fields)
    descriptor = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, (json.dumps(row) + '\n').encode())
    finally:
        os.close(descriptor)


def records():
    try:
        return [json.loads(line) for line in LOG.read_text().splitlines()]
    except (OSError, ValueError):
        return []


def await_event(predicate):
    deadline = time.monotonic() + 180
    while not predicate(records()):
        if time.monotonic() > deadline:
            raise SystemExit('fixture timed out waiting for a logical peer event')
        time.sleep(0.2 * float(os.environ.get('EVAL_TIME_SCALE', '1')))


def interrupted(number, _frame):
    name = signal.Signals(number).name
    record('interrupted', signal=name)
    print(f'{JOB}: caught {name}', flush=True)
    raise SystemExit(130 if number == signal.SIGINT else 143)


signal.signal(signal.SIGINT, interrupted)
signal.signal(signal.SIGTERM, interrupted)
if JOB == 'recover':
    record('recovered')
    (ROOT / 'recovery.txt').write_text('RECOVERED same live terminal\n')
    print('RECOVERED same live terminal', flush=True)
else:
    record('started')
    print(f'{JOB}: started', flush=True)
    await_event(lambda rows: all(any(row['job'] == job and row['event'] == 'started'
                                    for row in rows) for job in ('alpha', 'beta', 'hang')))
    if JOB == 'hang':
        record('hung_ready')
        print('HANG READY — interrupt this command, then recover in this same terminal', flush=True)
        while True:
            signal.pause()
    else:
        record('progress')
        print(f'{JOB}: progressed while hang was live', flush=True)
        await_event(lambda rows: any(row['event'] == 'recovered' for row in rows))
        line = f'{JOB.upper()} COMPLETE'
        (ROOT / f'{JOB}.txt').write_text(line + '\n')
        record('completed')
        print(line, flush=True)
