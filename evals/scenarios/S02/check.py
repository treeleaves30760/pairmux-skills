#!/usr/bin/env python3
"""S02 check. Pass = the build ran to completion via pairmux AND the transcript did not sleep-and-guess."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
TRANSCRIPT = sys.argv[1] if len(sys.argv) > 1 else ""
BUILD = evallib.fixture_name("slow-build.sh")

if not evallib.any_journal_has("BUILD COMPLETE"):
    evallib.fail("build never reached completion (BUILD COMPLETE not in any journal)")

# The whole point of S02: no fixed sleeps to guess when the build is done. Scoped to agent-ISSUED
# content (see evallib): the fixture itself contains `sleep 0.25`, so a prudent pre-execution Read
# of it echoes that into a tool_result — a fixture artifact, not the agent sleeping.
if not evallib.issued_forbids(TRANSCRIPT, evallib.SLEEP_GUESS):
    evallib.fail("transcript used a fixed 'sleep N' to guess build timing — use run/wait instead")

if not evallib.runner_trace_proves("S02"):
    evallib.fail(f"runner-owned proxy trace does not prove {BUILD} ran through pairmux")

evallib.passed("slow build completed and the agent waited without sleep-guessing")
