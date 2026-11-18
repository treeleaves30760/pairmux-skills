"""Fake slow build fixture for eval S02. Prints steady progress for ~BUILD_SECONDS, then a marker.

Windows twin of slow-build.sh. Cadence is 4 ticks/second, well under `wait --idle`'s 800ms default,
so idle-waits don't misfire.
"""
import os
import time

secs = int(os.environ.get("BUILD_SECONDS", "20"))
steps = secs * 4
print(f"==> building (fake, ~{secs}s)", flush=True)
for i in range(1, steps + 1):
    print(f"compiling module {i}/{steps}", flush=True)
    time.sleep(0.25)
print("BUILD COMPLETE", flush=True)
