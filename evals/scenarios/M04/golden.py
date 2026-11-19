#!/usr/bin/env python3
"""M04 private reference solution: two persistent pairmux shells, A (venv) and B (plain)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

if evallib.IS_WINDOWS:
    # PowerShell: dot-source the venv's Activate.ps1 (a process-scoped policy only matters on
    # hosts whose execution policy forbids local scripts) and assign the variable natively.
    ACTIVATE_A = ("Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; "
                  "cd a-work; . ..\\venv\\Scripts\\Activate.ps1")
    EXPORT_A = "$env:TOKEN = 'fixture-only-m04'"
    PREPARE_B = "Remove-Item Env:TOKEN, Env:VIRTUAL_ENV -ErrorAction SilentlyContinue; cd b-work"
    A_STEPS = {step: f"python ..\\identity.py {step}" for step in ("A1", "A2", "A3")}
    B_STEPS = {step: f"python ..\\identity.py {step}" for step in ("B1", "B2")}
else:
    ACTIVATE_A = "cd a-work; source ../venv/bin/activate"
    EXPORT_A = 'export TOKEN=fixture-only-m04'
    PREPARE_B = 'unset TOKEN VIRTUAL_ENV; cd b-work'
    A_STEPS = {
        'A1': 'python ../identity.py A1',
        'A2': 'python ../identity.py A2',
        'A3': 'python ../identity.py A3',
    }
    B_STEPS = {
        'B1': 'python3 ../identity.py B1',
        'B2': 'python3 ../identity.py B2',
    }

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
pmx = evallib.pmx

pmx("new", "--name", "m04a", "--cwd", str(SCEN_DIR))
pmx("new", "--name", "m04b", "--cwd", str(SCEN_DIR))
pmx("run", "m04a", ACTIVATE_A)
pmx("run", "m04a", EXPORT_A)
pmx("run", "m04b", PREPARE_B)
pmx("run", "m04a", A_STEPS['A1'])
pmx("run", "m04b", B_STEPS['B1'])
pmx("run", "m04a", A_STEPS['A2'])
pmx("run", "m04b", B_STEPS['B2'])
pmx("run", "m04a", A_STEPS['A3'])
pmx("kill", "--all")
