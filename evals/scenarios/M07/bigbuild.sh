#!/usr/bin/env bash
# M07 fixture: a plain, long, NON-interactive build. ~45s at scale 1.
# EVAL_TIME_SCALE (float, default 1) shrinks sleeps for infrastructure tests.
set -euo pipefail
scale="${EVAL_TIME_SCALE:-1}"
step=$(python3 -c "print(max(0.05, 5 * float('$scale')))")
rm -f build-out.txt
for i in $(seq 1 9); do
  echo "compiling module $i/9 ..."
  sleep "$step"
done
echo "linking ..."
echo "BUILD SUCCESS sha=b7e41c9" | tee build-out.txt
