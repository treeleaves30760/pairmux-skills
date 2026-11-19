#!/usr/bin/env python3
"""S09 — a terminal stuck on a hung command. The agent must interrupt it and reuse the SAME terminal."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "s09")

# Start a command that prints a marker and then hangs effectively forever. The same text is valid
# in POSIX shells and PowerShell (echo and sleep are Write-Output / Start-Sleep aliases there).
evallib.pmx("--json", "new", "--name", "worker", capture=True)
evallib.pmx("--json", "run", "worker", "echo WORKER-START; sleep 600", "--timeout", "3s",
            check=False, capture=True)
if not evallib.status_is("worker", "running"):
    raise SystemExit("error: S09 setup did not leave worker running")
print("S09 ready. Terminal 'worker' is hung on a long sleep after printing WORKER-START.")
