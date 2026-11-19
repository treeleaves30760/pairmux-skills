#!/usr/bin/env python3
"""M06 private reference solution: checkpoint, read the human revision, ack, ordered work."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
pmx, PY = evallib.pmx, evallib.PYTHON

pmx("new", "--name", "m06queue", "--cwd", str(SCEN_DIR))
pmx("run", "m06queue", f"{PY} queue.py checkpoint", "--timeout", "15s")
pmx("wait", "m06queue", "--idle", "150", "--timeout", "15s")
assert "HUMAN NOTE" in evallib.pmx_json("peek", "m06queue")["output"]
lines = (SCEN_DIR / "priority.txt").read_text(encoding="utf-8").splitlines()
revision = dict(line.strip().split("=", 1) for line in lines)["revision"]
pmx("run", "m06queue", f"{PY} queue.py ack {revision}")
for job in ("release", "tests", "docs"):
    pmx("run", "m06queue", f"{PY} queue.py work {job}", "--timeout", "15s")
pmx("kill", "--all")
