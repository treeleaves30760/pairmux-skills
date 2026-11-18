#!/usr/bin/env python3
"""S04 — [y/N] confirmation: recognise awaiting-input and answer it once."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "s04")
evallib.prepare_fixtures(__file__, SCEN_DIR)
fixture = SCEN_DIR / evallib.fixture_name("confirm.sh")
if not evallib.IS_WINDOWS and fixture.is_file():
    os.chmod(fixture, 0o755)
print(f"S04 ready. {fixture.name} asks a [y/N] question.")
