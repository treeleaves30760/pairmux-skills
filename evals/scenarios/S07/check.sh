#!/usr/bin/env bash
# S07 check. Pass = the 'report' terminal is back to an idle shell prompt (escaped the pager).
set -uo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "$SCEN_DIR/env.sh"

pmx_status_is report idle \
  || pmx_fail "terminal 'report' is not idle — the agent did not escape the pager"

pmx_pass "escaped the pager; terminal is idle again"
