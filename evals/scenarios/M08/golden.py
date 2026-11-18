#!/usr/bin/env python3
"""M08 private reference solution: server terminal, curl from a second terminal, readback, Ctrl-C."""
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.load_env(scen_dir=SCEN_DIR)
pmx, PY = evallib.pmx, evallib.PYTHON

pmx("new", "--name", "m08server", "--cwd", str(SCEN_DIR))
pmx("run", "m08server", f"{PY} server.py", "--timeout", "100ms")
# Readiness may land between a peek and a future-only pattern wait, so never arm one long wait:
# observe the current output first, then wait briefly for the event only while it is still ahead.
deadline = time.monotonic() + 30
while "READY http" not in evallib.pmx_json("peek", "m08server").get("output", ""):
    if time.monotonic() > deadline:
        raise SystemExit("golden: server never announced READY")
    pmx("wait", "m08server", "--pattern", "READY http", "--timeout", "1s", check=False, capture=True)

pmx("new", "--name", "m08client", "--cwd", str(SCEN_DIR))
# Expansion belongs to the live client shell, not this private driver.
if evallib.IS_WINDOWS:
    FETCH = ('curl.exe --fail --silent --show-error -o answer-server.txt '
             '"http://127.0.0.1:$((Get-Content server-port.txt).Trim())/status"')
else:
    FETCH = ('curl --fail --silent --show-error "http://127.0.0.1:$(cat server-port.txt)/status"'
             ' > answer-server.txt')
pmx("run", "m08client", FETCH, "--timeout", "15s")

output = evallib.pmx_json("log", "m08server", "--grep", "^REQUEST receipt=")["output"]
lines = [re.sub(r"^[0-9]+:", "", line) for line in output.splitlines()]
lines = [line for line in lines if line.startswith("REQUEST receipt=")]
assert len(lines) == 1, output
(SCEN_DIR / "answer-request.txt").write_text(lines[0] + "\n", encoding="utf-8")

pmx("send", "m08server", "--key", "C-c")
pmx("wait", "m08server", "--done", "--timeout", "15s")
pmx("kill", "--all")
