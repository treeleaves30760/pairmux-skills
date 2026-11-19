#!/usr/bin/env python3
"""S03 — one error line buried in a huge log: truncation pointer -> log --grep."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
evallib.setup(SCEN_DIR, "s03")

# Generate a 10,000-line haystack with exactly one FATAL line at a non-obvious position.
with open(SCEN_DIR / "haystack.log", "w", encoding="utf-8", newline="\n") as handle:
    for i in range(1, 10001):
        if i == 6137:
            handle.write("FATAL: shard 7 checksum mismatch (code E4231)\n")
        else:
            handle.write(f"INFO  line {i:05d} ok — processing record {i * 3}\n")
print("S03 ready. haystack.log has 10000 lines; exactly one contains FATAL / E4231.")
