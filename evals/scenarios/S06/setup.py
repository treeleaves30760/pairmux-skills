#!/usr/bin/env python3
"""S06 — Python REPL: drive an interactive interpreter with send/peek, not run."""
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "s06")
if not shutil.which(evallib.PYTHON):
    print(f"warning: {evallib.PYTHON} not on PATH; this scenario needs it.", file=sys.stderr)
print("S06 ready.")
