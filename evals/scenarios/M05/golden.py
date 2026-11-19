#!/usr/bin/env python3
"""M05 private reference solution: three live terminals, Ctrl-C and in-place recovery."""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
pmx, PY = evallib.pmx, evallib.PYTHON

for name in ("alpha", "beta", "hang"):
    pmx("new", "--name", f"m05{name}", "--cwd", str(SCEN_DIR))
    pmx("run", f"m05{name}", f"{PY} job.py {name}", "--timeout", "200ms")

# Fixture-internal logical subscriptions cover output that may precede a future
# pattern wait; the driver does not sleep or poll a terminal screen.
path = SCEN_DIR / "jobs.jsonl"
deadline = time.monotonic() + 15
while True:
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    except ValueError:
        # A job may be mid-append (Windows readers can see the extended, not yet written, tail).
        rows = []
    ready = any(row['event'] == 'hung_ready' for row in rows)
    ready = ready and all(any(row['job'] == job and row['event'] == 'progress' for row in rows)
                          for job in ('alpha', 'beta'))
    if ready:
        break
    assert time.monotonic() < deadline, rows
    time.sleep(0.2 * float(os.environ.get('EVAL_TIME_SCALE', '1')))

pmx("send", "m05hang", "--key", "C-c")
pmx("wait", "m05hang", "--idle", "150", "--timeout", "15s")
pmx("run", "m05hang", f"{PY} job.py recover", "--timeout", "15s")
pmx("wait", "m05alpha", "--idle", "150", "--timeout", "15s")
pmx("wait", "m05beta", "--idle", "150", "--timeout", "15s")
pmx("kill", "--all")
