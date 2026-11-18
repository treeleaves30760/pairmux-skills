#!/usr/bin/env python3
"""M01 — triage board: three concurrent jobs (server boot, test suite, log dig)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

FATAL = "2026-08-01T03:14:07Z FATAL: disk quota exceeded on shard-17 token=FT-55d1"
SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "m01")
evallib.prepare_fixtures(__file__, SCEN_DIR, terminal_support=evallib.IS_WINDOWS)
TESTS = evallib.fixture_name("slowtests.sh")
if not evallib.IS_WINDOWS:
    for name in ("bigserver.py", TESTS):
        os.chmod(SCEN_DIR / name, 0o755)
for path in SCEN_DIR.glob("answer-*.txt"):
    path.unlink()
for name in ("server-port.txt", "test-report.txt", "DONE.txt", "subgoals.json", "noisy.log",
             "m01-events.jsonl"):
    (SCEN_DIR / name).unlink(missing_ok=True)
if not shutil.which(evallib.PYTHON):
    print(f"warning: {evallib.PYTHON} not on PATH; this scenario needs it.", file=sys.stderr)
if not shutil.which("curl"):
    print("warning: curl not on PATH; this scenario needs it.", file=sys.stderr)

# Deterministic 10k-line log with exactly one FATAL line buried at line 6437.
with open(SCEN_DIR / "noisy.log", "w", encoding="utf-8", newline="\n") as handle:
    for i in range(1, 10001):
        if i == 6437:
            handle.write(FATAL + "\n")
        else:
            handle.write(f"2026-08-01T03:{(i // 300) % 60:02d}:{i % 60:02d}Z INFO worker-{i % 7} heartbeat seq={i}\n")

# Keep expected fixture hashes in the existing runner-owned env file, never a newly agent-visible
# checker companion. Manual runs use that same env file.
names = ["bigserver.py", TESTS, "noisy.log"] + (["termsupport.py"] if evallib.IS_WINDOWS else [])
hashes = {name: hashlib.sha256((SCEN_DIR / name).read_bytes()).hexdigest() for name in names}
with open(evallib.env_file_path(SCEN_DIR), "a", encoding="utf-8", newline="\n") as handle:
    handle.write("# M01 fixture-hashes " + json.dumps(hashes, sort_keys=True) + "\n")
print(f"M01 ready. Jobs: bigserver.py (live listener approval), {TESTS} (42 checks), noisy.log (10k lines).")
