#!/usr/bin/env python3
"""M07 — long non-interactive build (the honest control scenario: every harness should complete
it; the interesting data is the efficiency metrics)."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "m07")
evallib.prepare_fixtures(__file__, SCEN_DIR)
BUILD = evallib.fixture_name("bigbuild.sh")
if not evallib.IS_WINDOWS:
    fixture = SCEN_DIR / BUILD
    os.chmod(fixture, fixture.stat().st_mode | 0o111)
for name in ("build-out.txt", "answer-build.txt", "subgoals.json"):
    (SCEN_DIR / name).unlink(missing_ok=True)
print(f"M07 ready. {BUILD} is a plain long build.")
