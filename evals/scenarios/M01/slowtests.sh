#!/usr/bin/env bash
# M01 fixture: a test suite that takes ~18s at scale 1 and writes a report.
set -euo pipefail
scale="${EVAL_TIME_SCALE:-1}"
step=$(python3 -c "print(max(0.05, 1 * float('$scale')))")
rm -f test-report.txt
for i in $(seq 1 18); do
  echo "test batch $i/18 ok"
  sleep "$step"
done
echo "TESTS PASSED 42/42 token=TP-9c2e" | tee test-report.txt
