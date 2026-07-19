#!/usr/bin/env bash
# S07 check. Pass = the 'report' terminal is back to an idle shell prompt (escaped the pager).
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"

pmx_status_is report idle \
  || pmx_fail "terminal 'report' is not idle — the agent did not escape the pager"

pmx_runner_trace_proves S07 \
  || pmx_fail "runner-owned proxy trace does not prove q was sent to report"

pmx_pass "escaped the pager; terminal is idle again"
