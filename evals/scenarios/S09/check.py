#!/usr/bin/env python3
"""S09 check. Pass = the SAME 'worker' terminal shows both the original start marker and the recovery
marker. WORKER-RECOVERED can only appear if the hung command was actually interrupted first (one
command runs per terminal), so its presence proves recovery rather than kill+new."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)

if not evallib.journal_has("worker", "WORKER-START"):
    evallib.fail("'worker' journal missing WORKER-START — wrong terminal?")

if not evallib.journal_has("worker", "WORKER-RECOVERED"):
    evallib.fail("'worker' never ran the recovery command — the hung command was not cleared in place")

if not evallib.runner_trace_proves("S09"):
    evallib.fail("runner-owned proxy trace does not prove C-c preceded recovery on worker")

evallib.passed("interrupted the hung command and recovered the same terminal")
