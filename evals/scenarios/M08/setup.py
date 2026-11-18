#!/usr/bin/env python3
"""M08 — a slow localhost-only stdlib server with exact request readback."""
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "m08")
for name in ("server-events.jsonl", "server-port.txt", "server.pid", "requests.log",
             "answer-server.txt", "answer-request.txt", "subgoals.json"):
    (SCEN_DIR / name).unlink(missing_ok=True)
evallib.prepare_fixtures(__file__, SCEN_DIR, terminal_support=True)
if not evallib.IS_WINDOWS:
    fixture = SCEN_DIR / "server.py"
    os.chmod(fixture, fixture.stat().st_mode | 0o111)
if not shutil.which("curl"):  # curl.exe ships with Windows 10 1803 and later
    raise SystemExit("error: M08 requires curl")
print("M08 ready: a slow localhost-only stdlib server with exact request readback.")
