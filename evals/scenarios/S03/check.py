#!/usr/bin/env python3
"""S03 check. Pass = the file was displayed through pairmux AND the agent reported the FATAL code."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
TRANSCRIPT = sys.argv[1] if len(sys.argv) > 1 else ""

# The agent must have run the display through pairmux (the 10k lines land in the journal).
if not evallib.any_journal_has("code E4231"):
    evallib.fail("haystack was never displayed through pairmux (E4231 not in any journal)")

# And it must have reported the specific error code it could only get by querying the journal.
if not evallib.runner_trace_proves("S03"):
    evallib.fail("runner-owned proxy trace does not prove display plus log --grep")

if not evallib.issued_requires(TRANSCRIPT, "E4231"):
    evallib.fail("agent did not report the FATAL error code E4231")

evallib.passed("found and reported the buried FATAL line")
