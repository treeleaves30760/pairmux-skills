#!/usr/bin/env python3
"""M02 private reference solution: all interactions go through a real pairmux PTY."""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

EXPRESSION = '1234 * 5678'

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
pmx, PY = evallib.pmx, evallib.PYTHON

pmx("new", "--name", "m02chain", "--cwd", str(SCEN_DIR))
pmx("run", "m02chain", f"{PY} flow.py repl", "--timeout", "2s")
pmx("send", "m02chain", "--text", EXPRESSION, "--enter")
pmx("wait", "m02chain", "--idle", "150", "--timeout", "15s")
output = evallib.pmx_json("peek", "m02chain")["output"]
# A multi-line paste can leave the REPL's continuation prompts on the result line.
values = re.findall(r"(?m)(?:^|>>> )([0-9]+)\r?$", output)
assert values, output
value = values[-1]
(SCEN_DIR / "answer-value.txt").write_text(value + "\n", encoding="utf-8")
pmx("send", "m02chain", "--text", "exit()", "--enter")
pmx("wait", "m02chain", "--idle", "150", "--timeout", "15s")
pmx("run", "m02chain", f"{PY} flow.py deploy {value}", "--timeout", "2s")
pmx("send", "m02chain", "--text", "Y", "--enter")
pmx("wait", "m02chain", "--idle", "150", "--timeout", "15s")
assert "(END)" in evallib.pmx_json("peek", "m02chain")["output"]
pmx("send", "m02chain", "--text", "q")
pmx("wait", "m02chain", "--idle", "150", "--timeout", "15s")
pmx("kill", "--all")
