#!/usr/bin/env python3
"""M07 golden path — reference pairmux solution used by evals/test_scenarios.py to prove the
fixtures and check agree. Not visible to agents."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
pmx = evallib.pmx

if evallib.IS_WINDOWS:
    BUILD = "python bigbuild.py"
    ANSWER = "Get-Content build-out.txt -Tail 1 | Set-Content -Encoding ascii answer-build.txt"
else:
    BUILD = "./bigbuild.sh"
    ANSWER = "tail -1 build-out.txt > answer-build.txt"

pmx("new", "--name", "m07build", "--cwd", str(SCEN_DIR))
pmx("run", "m07build", BUILD, "--timeout", "180s")
pmx("run", "m07build", ANSWER)
pmx("kill", "m07build")
