#!/usr/bin/env bash
# M03 fixture: independent job B (~12s at scale 1). Must also be completed.
set -euo pipefail
scale="${EVAL_TIME_SCALE:-1}"
step=$(python3 -c "print(max(0.05, 12 * float('$scale')))")
printf 'start=%s\n' "$(date +%s)" >sidework-b.txt
echo "sidework B: compacting event store ..."
sleep "$step"
printf 'SIDEWORK-B COMPLETE token=SB-77cd end=%s\n' "$(date +%s)" >>sidework-b.txt
echo "sidework B done"
