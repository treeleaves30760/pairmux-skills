#!/usr/bin/env python3
"""M05 — two cooperative jobs and one interruptible hang."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "m05")
for name in ("jobs.jsonl", "alpha.txt", "beta.txt", "recovery.txt", "subgoals.json"):
    (SCEN_DIR / name).unlink(missing_ok=True)
evallib.prepare_fixtures(__file__, SCEN_DIR, terminal_support=True)
if not evallib.IS_WINDOWS:
    fixture = SCEN_DIR / "job.py"
    os.chmod(fixture, fixture.stat().st_mode | 0o111)
print("M05 ready: two cooperative jobs and one interruptible hang.")
