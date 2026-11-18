#!/usr/bin/env python3
"""S01 — instant command: the basic loop with no detours."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
env = evallib.setup(SCEN_DIR, "s01")
print(f"S01 ready. Isolated socket={env['PAIRMUX_SOCKET']} state={env['PAIRMUX_STATE_DIR']}")
