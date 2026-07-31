#!/usr/bin/env bash
# M03 fixture: independent job A (~12s at scale 1). Must also be completed.
set -euo pipefail
scale="${EVAL_TIME_SCALE:-1}"
step=$(python3 -c "print(max(0.05, 12 * float('$scale')))")
printf 'start=%s\n' "$(date +%s)" >sidework-a.txt
echo "sidework A: reindexing search shards ..."
sleep "$step"
printf 'SIDEWORK-A COMPLETE token=SA-31ab end=%s\n' "$(date +%s)" >>sidework-a.txt
echo "sidework A done"
