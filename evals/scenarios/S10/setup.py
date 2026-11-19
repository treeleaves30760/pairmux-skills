#!/usr/bin/env python3
"""S10 — note relay: a human left an instruction as a note; the agent must read it and act on it."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "s10")
(SCEN_DIR / "token.txt").unlink(missing_ok=True)

# Create the terminal and leave the human's message on it.
evallib.pmx("--json", "new", "--name", "handoff", capture=True)
evallib.pmx("--json", "note", "handoff",
            "The staging deploy token is ZT-9QK. Please write exactly that token into a file named "
            "token.txt in the working directory.", capture=True)
print("S10 ready. Terminal 'handoff' has a note waiting.")
