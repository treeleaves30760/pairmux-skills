#!/usr/bin/env python3
"""M07 check — harness-agnostic artifacts only (no pairmux journal assertions): the build ran to
completion and the agent recorded its exact success line."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
EXPECTED = "BUILD SUCCESS sha=b7e41c9"


def lines(name):
    path = SCEN_DIR / name
    try:
        if evallib.IS_WINDOWS:
            return evallib.read_answer(path).splitlines()
        return path.read_bytes().decode("utf-8", errors="replace").splitlines()
    except (OSError, UnicodeError):
        return None


ledger = evallib.Subgoals()
build = lines("build-out.txt")
ledger.add("build_completed", build is not None and any(EXPECTED in line for line in build),
           "capability: build-out.txt must contain the success line (build ran to completion)")

answer = lines("answer-build.txt")
first = ""
if answer is not None:
    # tr -d '\r' | trim each line | drop blank lines | head -1
    stripped = [line.replace("\r", "").strip() for line in answer]
    first = next((line for line in stripped if line), "")
ledger.add("answer_exact", first == EXPECTED, f"capability: answer-build.txt must contain exactly: {EXPECTED}")
ledger.finish()
