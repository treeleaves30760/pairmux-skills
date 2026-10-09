#!/usr/bin/env bash
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
verdicts="$(python3 -I - "$SCEN_DIR" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
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
        return (root / name).read_text().strip()
    except OSError:
        return ''

valid = bool(rows) and all(all(isinstance(row.get(key), int) and row[key] > 1 for key in ('pid', 'ppid', 'sid'))
    and str(row.get('tty', '')).startswith('/dev/') and row.get('cwd') == str(root) for row in rows)
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
for verdict in (overlap, trapped, same, peers, complete):
    print(int(bool(verdict)))
PY
)"
IFS=$'\n' read -r -d '' -a flags < <(printf '%s\n' "$verdicts") || true
pmx_subgoal three_jobs_overlap "${flags[0]:-0}" 'capability: three distinct PTYs overlapped and both peers progressed before interrupt'
pmx_subgoal sigint_trapped "${flags[1]:-0}" 'capability: the original hang process trapped SIGINT, not termination/destruction'
pmx_subgoal same_terminal_reused "${flags[2]:-0}" 'capability: recovery retained the exact shell PID/session/PTY/cwd'
pmx_subgoal other_jobs_unaffected "${flags[3]:-0}" 'capability: both original peer processes completed without interruption'
pmx_subgoal recovery_complete "${flags[4]:-0}" 'capability: real in-place recovery unblocked both peers'
pmx_subgoals_finish
