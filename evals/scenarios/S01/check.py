#!/usr/bin/env python3
"""S01 check. Pass = some terminal printed PAIRMUX-S01-OK via pairmux. Optional argv[1] = transcript."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
TRANSCRIPT = sys.argv[1] if len(sys.argv) > 1 else ""

if not evallib.any_journal_has("PAIRMUX-S01-OK"):
    evallib.fail("expected marker PAIRMUX-S01-OK not found in any terminal journal "
                 "(did the agent run it via pairmux?)")

# Basic loop should not sleep-and-guess for an instant command.
if not evallib.transcript_forbids(TRANSCRIPT, evallib.SLEEP_GUESS):
    evallib.fail("transcript used a fixed sleep to guess timing")

if not evallib.runner_trace_proves("S01"):
    evallib.fail("runner-owned proxy trace does not prove a successful S01 run")

if not evallib.issued_requires(TRANSCRIPT, r"exit([\s_-]*code)?[^0-9]*0|status[^0-9A-Za-z]*done"):
    evallib.fail("agent did not report/confirm pairmux exit code 0")

evallib.passed("instant command ran and completed via pairmux")
