#!/usr/bin/env python3
"""M06 check. Only the checker/control plane reads this private runner environment."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
env = evallib.load_env(scen_dir=SCEN_DIR)
root = SCEN_DIR.resolve()
private = (Path(env.get("PAIRMUX_STATE_DIR", "")) / "m06-human").resolve()


def text(path):
    try:
        return evallib.read_answer(path).strip()
    except (OSError, UnicodeError):
        return ''


try:
    rows = [json.loads(line) for line in (root / 'queue.jsonl').read_text(encoding="utf-8").splitlines()]
    proof = json.loads((private / 'revision.json').read_text(encoding="utf-8"))
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
    and str(row.get('tty', '')).startswith(evallib.TTY_PREFIX) and evallib.same_path(row.get('cwd'), root) for row in rows)
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

# The owned companion retains its PID; stop only that process, no host-wide process sweep.
try:
    evallib.terminate_pid(int(text(private / 'human.pid')))
except ValueError:
    pass

ledger = evallib.Subgoals()
ledger.add('live_checkpoint', bool(checkpoint_ok), 'capability: actual terminal process reached checkpoint and printed the live note')
ledger.add('human_revision', bool(human), 'capability: private runner human changed priority only after that logical checkpoint')
ledger.add('revision_acknowledged', bool(acknowledged), 'capability: the same terminal acknowledged the exact observed human revision')
ledger.add('priority_order', bool(order), 'capability: release then tests then docs, with actual ordered process events')
ledger.add('work_completed', bool(complete), 'capability: all revised work finished with fixture-produced outputs')
ledger.finish()
