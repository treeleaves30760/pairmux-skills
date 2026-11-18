#!/usr/bin/env python3
"""M04 — stdlib venv, source/export observer, and independent work directories."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
env = evallib.setup(SCEN_DIR, "m04")
for name in ("identity.jsonl", "environment.jsonl", "a-first.txt", "a-second.txt", "a-third.txt",
             "b-first.txt", "b-second.txt", "subgoals.json"):
    (SCEN_DIR / name).unlink(missing_ok=True)
(SCEN_DIR / "a-work").mkdir(parents=True, exist_ok=True)
(SCEN_DIR / "b-work").mkdir(parents=True, exist_ok=True)
evallib.prepare_fixtures(__file__, SCEN_DIR, terminal_support=True)

python = shutil.which(evallib.PYTHON) or sys.executable
subprocess.run([python, "-I", "-m", "venv", "--without-pip", str(SCEN_DIR / "venv")], check=True)

# Append the trusted source observer without replacing the stdlib activation. Keep source hashes
# in the private state; no agent-written evidence is trusted when either this observer or the real
# activation/interpreter fixture changed.
root = SCEN_DIR.resolve()
state = Path(env["PAIRMUX_STATE_DIR"]).resolve()
if evallib.IS_WINDOWS:
    activation = root / "venv" / "Scripts" / "Activate.ps1"
    text = activation.read_text(encoding="utf-8-sig")
    # The stdlib script is Authenticode-signed; an appended stanza would void the signature, so
    # drop the signature block and leave an ordinary local script.
    cut = text.find("# SIG # Begin signature block")
    if cut >= 0:
        text = text[:cut]

    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    text += ("\n# M04 once-only activation/export evidence\n"
             f"$global:_M04_ROOT = {literal(str(root))}\n"
             f"$global:_M04_PYTHON = {literal(python)}\n"
             ". (Join-Path $global:_M04_ROOT 'observe-env.ps1')\n")
    # A byte-order mark keeps Windows PowerShell 5.1 reading the file as UTF-8.
    activation.write_text(text, encoding="utf-8-sig")
    files = ("identity.py", "observe-env.ps1", "venv/Scripts/Activate.ps1")
else:
    activation = root / "venv" / "bin" / "activate"
    # Stdlib exports intentionally precede our later wrapper definition.
    activation.write_text("# shellcheck disable=SC2218\n" + activation.read_text())
    with activation.open("a") as handle:
        handle.write("\n# M04 once-only source/export evidence\n")
        handle.write(f"_M04_ROOT={shlex.quote(str(root))}\n")
        handle.write(f"_M04_PYTHON={shlex.quote(shutil.which('python3') or sys.executable)}\n")
        handle.write(f"# shellcheck source={root}/observe-env.sh\n")
        handle.write('. "$_M04_ROOT/observe-env.sh"\n')
    files = ("identity.py", "observe-env.sh", "venv/bin/activate")
(state / "m04-fixture-hashes.json").write_text(json.dumps(
    {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}) + "\n")
if not evallib.IS_WINDOWS:
    fixture = SCEN_DIR / "identity.py"
    os.chmod(fixture, fixture.stat().st_mode | 0o111)
print("M04 ready: stdlib venv, source/export observer, and independent work directories.")
