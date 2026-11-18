#!/usr/bin/env python3
"""S07 — a terminal left stuck in a pager. The agent must recognise it and escape with q."""
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "s07")

# Create a terminal and leave it parked inside a pager (awaiting-input at a pager prompt). POSIX uses
# the real `less`; Windows has no less, so a stdlib pager fixture shows the same (END) prompt.
if evallib.IS_WINDOWS:
    evallib.prepare_fixtures(__file__, SCEN_DIR, terminal_support=True)
    command = f'{evallib.PYTHON} "{SCEN_DIR / "pager.py"}"'
else:
    if not shutil.which("less"):
        raise SystemExit("error: S07 requires less")
    command = "seq 500 | less"
evallib.pmx("--json", "new", "--name", "report", capture=True)
evallib.pmx("--json", "run", "report", command, "--timeout", "3s", check=False, capture=True)
if not evallib.status_is("report", "awaiting-input"):
    raise SystemExit("error: S07 setup did not leave report at a pager prompt")
print("S07 ready. Terminal 'report' is stuck in a pager.")
