#!/usr/bin/env python3
"""M02 — a live REPL calculation, a deployment confirmation and an embedded pager."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "m02")
for name in ("interaction.jsonl", "deployment.txt", "answer-value.txt", "subgoals.json"):
    (SCEN_DIR / name).unlink(missing_ok=True)
evallib.prepare_fixtures(__file__, SCEN_DIR, terminal_support=True)
if not evallib.IS_WINDOWS:
    fixture = SCEN_DIR / "flow.py"
    os.chmod(fixture, fixture.stat().st_mode | 0o111)
print("M02 ready: a live calculation, a deployment confirmation, and an embedded pager.")
