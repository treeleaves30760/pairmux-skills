#!/usr/bin/env python3
"""S10 check. Pass = the agent read the note (only there could it learn the token) and carried out its
instruction: token.txt now contains ZT-9QK."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)

if not evallib.index_has("handoff", "ZT-9QK"):
    evallib.fail("the note was never present on 'handoff' (setup problem?)")

token = SCEN_DIR / "token.txt"
if not token.is_file():
    evallib.fail("token.txt was not created — the agent did not act on the note")

# Exact bytes on POSIX. On Windows, evallib.read_answer also accepts what native tools write
# (PowerShell's UTF-16/BOM output and CRLF line ends) before applying the same rule.
try:
    content = evallib.read_answer(token)
except (OSError, UnicodeError):
    content = None
if content not in ("ZT-9QK", "ZT-9QK\n"):
    evallib.fail("token.txt must contain exactly the note token ZT-9QK, with at most one trailing newline")

if not evallib.runner_trace_proves("S10"):
    evallib.fail("runner-owned proxy trace does not prove the handoff note was read")

evallib.passed("read the human's note and carried out its instruction")
