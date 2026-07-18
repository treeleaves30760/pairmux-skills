#!/usr/bin/env bash
# Fake slow build fixture for eval S02. Prints steady progress for ~BUILD_SECONDS, then a marker.
# Cadence is 4 ticks/second, well under `wait --idle`'s 800ms default, so idle-waits don't misfire.
set -u
secs="${BUILD_SECONDS:-20}"
steps=$(( secs * 4 ))
echo "==> building (fake, ~${secs}s)"
i=0
while [ "$i" -lt "$steps" ]; do
  i=$(( i + 1 ))
  printf 'compiling module %d/%d\n' "$i" "$steps"
  sleep 0.25
done
echo "BUILD COMPLETE"
