#!/usr/bin/env python3
"""M06 — initial docs/tests/release queue; a private human revises it at the live checkpoint."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
env = evallib.setup(SCEN_DIR, "m06")
for name in ("queue.jsonl", "checkpoint.json", "priority.txt", "human-note.txt", "release.txt",
             "tests.txt", "docs.txt", "subgoals.json"):
    (SCEN_DIR / name).unlink(missing_ok=True)
private = Path(env["PAIRMUX_STATE_DIR"]) / "m06-human"
private.mkdir(parents=True, exist_ok=True)
(SCEN_DIR / "priority.txt").write_text("revision=initial\norder=docs,tests,release\n")
evallib.prepare_fixtures(__file__, SCEN_DIR, terminal_support=True)
if not evallib.IS_WINDOWS:
    fixture = SCEN_DIR / "queue.py"
    os.chmod(fixture, fixture.stat().st_mode | 0o111)
human = evallib.spawn_detached(
    evallib.python_argv(evallib.script_dir(__file__) / "human.py", str(SCEN_DIR), str(private)),
    log_path=private / "human.log")
(private / "human.pid").write_text(f"{human.pid}\n")
print("M06 ready: initial docs/tests/release queue; a human will revise it at the live checkpoint.")
