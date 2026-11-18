#!/usr/bin/env python3
"""S02 — slow command (~20s fake build): must wait, never sleep-and-guess."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "s02")
evallib.prepare_fixtures(__file__, SCEN_DIR)
build = SCEN_DIR / evallib.fixture_name("slow-build.sh")
if not evallib.IS_WINDOWS and build.is_file():
    os.chmod(build, 0o755)
print(f"S02 ready. {build.name} takes ~20s and prints BUILD COMPLETE.")
