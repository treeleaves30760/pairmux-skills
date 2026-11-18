#!/usr/bin/env python3
"""S07 check. Pass = the 'report' terminal is back to an idle shell prompt (escaped the pager)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)

if not evallib.status_is("report", "idle"):
    evallib.fail("terminal 'report' is not idle — the agent did not escape the pager")

if not evallib.runner_trace_proves("S07"):
    evallib.fail("runner-owned proxy trace does not prove q was sent to report")

evallib.passed("escaped the pager; terminal is idle again")
