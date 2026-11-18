#!/usr/bin/env python3
"""M05 check. Fixture evidence only: overlap, SIGINT trap, same-terminal reuse, peers, recovery."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

root = evallib.scenario_dir(__file__).resolve()
try:
    rows = [json.loads(line) for line in (root / 'jobs.jsonl').read_text().splitlines()]
except (OSError, ValueError):
    rows = []


def one(job, event):
    found = [row for row in rows if row.get('job') == job and row.get('event') == event]
    return found[0] if len(found) == 1 else {}


def stamp(row):
    return row.get('time_ns', 0)


def identity(row):
    return tuple(row.get(key) for key in ('ppid', 'sid', 'tty', 'cwd'))


def text(name):
    try:
        return evallib.read_answer(root / name).strip()
    except (OSError, UnicodeError):
        return ''


valid = bool(rows) and all(all(isinstance(row.get(key), int) and row[key] > 1 for key in ('pid', 'ppid', 'sid'))
    and str(row.get('tty', '')).startswith(evallib.TTY_PREFIX) and evallib.same_path(row.get('cwd'), root) for row in rows)
starts = [one(job, 'started') for job in ('alpha', 'beta', 'hang')]
progress = [one(job, 'progress') for job in ('alpha', 'beta')]
hang, ready, interrupt, reuse = (one('hang', 'started'), one('hang', 'hung_ready'),
                                  one('hang', 'interrupted'), one('recover', 'recovered'))
overlap = valid and all(starts) and len({row.get('tty') for row in starts}) == 3
# Peer progress occurs after all jobs started but before any interruption.
overlap = overlap and all(max(map(stamp, starts)) < stamp(row) < stamp(interrupt) for row in progress)
trapped = valid and interrupt.get('signal') == 'SIGINT' and hang.get('pid') == ready.get('pid') == interrupt.get('pid')
trapped = trapped and identity(hang) == identity(interrupt) and 0 < stamp(hang) < stamp(ready) < stamp(interrupt)
same = trapped and identity(interrupt) == identity(reuse) and reuse.get('pid') != hang.get('pid')
same = same and stamp(interrupt) < stamp(reuse) and identity(ready) == identity(hang)
peers = valid and not any(row.get('event') == 'interrupted' and row.get('job') != 'hang' for row in rows)
for job in ('alpha', 'beta'):
    start, advance, finish = one(job, 'started'), one(job, 'progress'), one(job, 'completed')
    peers = peers and start.get('pid') == advance.get('pid') == finish.get('pid') and bool(start)
    peers = peers and identity(start) == identity(advance) == identity(finish)
    peers = peers and 0 < stamp(start) < stamp(advance) < stamp(interrupt) < stamp(reuse) < stamp(finish)
    peers = peers and text(f'{job}.txt') == f'{job.upper()} COMPLETE'
complete = overlap and same and peers and text('recovery.txt') == 'RECOVERED same live terminal'

ledger = evallib.Subgoals()
ledger.add('three_jobs_overlap', bool(overlap), 'capability: three distinct PTYs overlapped and both peers progressed before interrupt')
ledger.add('sigint_trapped', bool(trapped), 'capability: the original hang process trapped SIGINT, not termination/destruction')
ledger.add('same_terminal_reused', bool(same), 'capability: recovery retained the exact shell PID/session/PTY/cwd')
ledger.add('other_jobs_unaffected', bool(peers), 'capability: both original peer processes completed without interruption')
ledger.add('recovery_complete', bool(complete), 'capability: real in-place recovery unblocked both peers')
ledger.finish()
