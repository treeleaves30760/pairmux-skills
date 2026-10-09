#!/usr/bin/env bash
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
# Only the checker/control plane sources this private runner environment.
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
verdicts="$(python3 -I - "$SCEN_DIR" "$PAIRMUX_STATE_DIR/m06-human" <<'PY'
import json
import os
from pathlib import Path
import signal
import sys

root, private = (Path(arg).resolve() for arg in sys.argv[1:])
def text(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ''
try:
    rows = [json.loads(line) for line in (root / 'queue.jsonl').read_text().splitlines()]
    proof = json.loads((private / 'revision.json').read_text())
except (OSError, ValueError):
    rows, proof = [], {}

def one(event):
    found = [row for row in rows if row.get('event') == event]
    return found[0] if len(found) == 1 else {}

def stamp(row):
    return row.get('time_ns', 0)

def identity(row):
    return tuple(row.get(key) for key in ('ppid', 'sid', 'tty', 'cwd'))

checkpoint, observed, ack = (one(event) for event in ('checkpoint', 'note_observed', 'acknowledged'))
valid = bool(rows) and all(all(isinstance(row.get(key), int) and row[key] > 1 for key in ('pid', 'ppid', 'sid'))
    and str(row.get('tty', '')).startswith('/dev/') and row.get('cwd') == str(root) for row in rows)
checkpoint_ok = valid and checkpoint.get('revision') == 'initial' and checkpoint.get('pid') == observed.get('pid')
checkpoint_ok = checkpoint_ok and identity(checkpoint) == identity(observed)
checkpoint_ok = checkpoint_ok and 0 < stamp(checkpoint) < stamp(observed)
revision = proof.get('revision', '')
human = checkpoint_ok and proof.get('checkpoint') == checkpoint and str(revision).startswith('human-')
human = human and proof.get('order') == ['release', 'tests', 'docs'] and proof.get('human_pid', 0) > 1
human = human and text(private / 'human.pid') == str(proof.get('human_pid'))
human = human and stamp(checkpoint) < stamp(proof) < stamp(observed) and observed.get('revision') == revision
human = human and observed.get('note') == proof.get('note') == text(root / 'human-note.txt')
human = human and text(root / 'priority.txt') == f'revision={revision}\norder=release,tests,docs'
acknowledged = human and ack.get('revision') == revision and identity(ack) == identity(checkpoint)
acknowledged = acknowledged and stamp(observed) < stamp(ack)
starts = [row for row in rows if row.get('event') == 'started']
finishes = [row for row in rows if row.get('event') == 'completed']
order = acknowledged and [row.get('job') for row in starts] == proof.get('order')
order = order and [row.get('job') for row in finishes] == proof.get('order')
if order:
    previous = stamp(ack)
    for start, finish in zip(starts, finishes):
        order = order and previous < stamp(start) < stamp(finish) and start.get('pid') == finish.get('pid')
        order = order and start.get('revision') == finish.get('revision') == revision
        order = order and identity(start) == identity(finish) == identity(checkpoint)
        previous = stamp(finish)
complete = order and all(text(root / f'{job}.txt') == f'COMPLETE {job} revision={revision}' for job in proof.get('order', []))
for verdict in (checkpoint_ok, human, acknowledged, order, complete):
    print(int(bool(verdict)))
# The owned companion uses exec, retaining its PID; no host-wide process sweep.
try:
    pid = int(text(private / 'human.pid'))
    if pid > 1:
        os.kill(pid, signal.SIGTERM)
except (OSError, ValueError):
    pass
PY
)"
IFS=$'\n' read -r -d '' -a flags < <(printf '%s\n' "$verdicts") || true
pmx_subgoal live_checkpoint "${flags[0]:-0}" 'capability: actual terminal process reached checkpoint and printed the live note'
pmx_subgoal human_revision "${flags[1]:-0}" 'capability: private runner human changed priority only after that logical checkpoint'
pmx_subgoal revision_acknowledged "${flags[2]:-0}" 'capability: the same terminal acknowledged the exact observed human revision'
pmx_subgoal priority_order "${flags[3]:-0}" 'capability: release then tests then docs, with actual ordered process events'
pmx_subgoal work_completed "${flags[4]:-0}" 'capability: all revised work finished with fixture-produced outputs'
pmx_subgoals_finish
