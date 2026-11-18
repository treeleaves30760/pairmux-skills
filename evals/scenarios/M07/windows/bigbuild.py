#!/usr/bin/env python3
"""M07 fixture (Windows twin of bigbuild.sh): a plain, long, NON-interactive build. ~45s at scale 1.

EVAL_TIME_SCALE (float, default 1) shrinks sleeps for infrastructure tests.
"""
import os
from pathlib import Path
import time

step = max(0.05, 5 * float(os.environ.get("EVAL_TIME_SCALE", "1")))
output = Path("build-out.txt")
output.unlink(missing_ok=True)
for i in range(1, 10):
    print(f"compiling module {i}/9 ...", flush=True)
    time.sleep(step)
print("linking ...", flush=True)
line = "BUILD SUCCESS sha=b7e41c9"
with output.open("w", encoding="utf-8", newline="\n") as handle:
    handle.write(line + "\n")
print(line, flush=True)
