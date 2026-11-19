#!/usr/bin/env python3
"""S06 check. Pass = the REPL evaluated the expression (result 7006652 appears in a journal)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
TRANSCRIPT = sys.argv[1] if len(sys.argv) > 1 else ""

if not evallib.any_journal_has("7006652"):
    evallib.fail("the REPL result 7006652 was not produced (did the agent drive the live REPL?)")

if not evallib.transcript_forbids(TRANSCRIPT, evallib.SLEEP_GUESS):
    evallib.fail("transcript used a fixed sleep instead of peeking for the REPL output")

if not evallib.runner_trace_proves("S06"):
    evallib.fail("runner-owned proxy trace does not prove REPL evaluation plus clean exit")

if not evallib.any_journal_has(">>>"):
    evallib.fail("Python REPL prompt was not observed in terminal state")

evallib.passed("drove the Python REPL, read back the result, and exited cleanly")
