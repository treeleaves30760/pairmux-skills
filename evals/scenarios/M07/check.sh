#!/usr/bin/env bash
# M07 check — harness-agnostic artifacts only (no pairmux journal assertions):
# the build ran to completion and the agent recorded its exact success line.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"

expected="BUILD SUCCESS sha=b7e41c9"

ok=0
[ -f "$SCEN_DIR/build-out.txt" ] && grep -qF "$expected" "$SCEN_DIR/build-out.txt" && ok=1
pmx_subgoal build_completed "$ok" "build-out.txt must contain the success line (build ran to completion)"

ok=0
if [ -f "$SCEN_DIR/answer-build.txt" ]; then
  answer="$(tr -d '\r' < "$SCEN_DIR/answer-build.txt" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | grep -v '^$' | head -1)"
  [ "$answer" = "$expected" ] && ok=1
fi
pmx_subgoal answer_exact "$ok" "answer-build.txt must contain exactly: $expected"

pmx_subgoals_finish
