#!/usr/bin/env python3
"""S04 check. Pass = the agent answered the prompt and the script proceeded (CONFIRMED, not ABORTED)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
TRANSCRIPT = sys.argv[1] if len(sys.argv) > 1 else ""

if not evallib.any_journal_has("CONFIRMED-DELETING"):
    evallib.fail("the confirmation was never answered 'yes' (CONFIRMED-DELETING absent)")

if evallib.any_journal_has("ABORTED"):
    evallib.fail("the script aborted — the prompt was answered no/empty instead of yes")

# Answering a prompt should not require sleeping to guess timing.
if not evallib.transcript_forbids(TRANSCRIPT, evallib.SLEEP_GUESS):
    evallib.fail("transcript used a fixed sleep instead of reacting to awaiting-input")

if not evallib.runner_trace_proves("S04"):
    evallib.fail("runner-owned proxy trace does not prove one yes answer on the prompt terminal")

evallib.passed("recognised the [y/N] prompt and answered it correctly")
