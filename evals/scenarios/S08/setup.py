#!/usr/bin/env python3
"""S08 — background server + client + journal readback across two terminals."""
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "s08")
evallib.prepare_fixtures(__file__, SCEN_DIR)
server, client = (SCEN_DIR / evallib.fixture_name(name) for name in ("server.sh", "hit.sh"))
if not evallib.IS_WINDOWS:
    for fixture in (server, client):
        if fixture.is_file():
            os.chmod(fixture, 0o755)
(SCEN_DIR / "port.txt").unlink(missing_ok=True)
if not shutil.which(evallib.PYTHON):
    print(f"warning: {evallib.PYTHON} not on PATH; this scenario needs it.", file=sys.stderr)
if not evallib.IS_WINDOWS and not shutil.which("curl"):
    print("warning: curl not on PATH; this scenario needs it.", file=sys.stderr)
print(f"S08 ready. {server.name} starts a background server; {client.name} sends one request.")
