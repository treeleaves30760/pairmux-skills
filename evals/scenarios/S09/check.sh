#!/usr/bin/env bash
# S09 check. Pass = the SAME 'worker' terminal shows both the original start marker and the recovery
# marker. WORKER-RECOVERED can only appear if the hung command was actually interrupted first
# (one command runs per terminal), so its presence proves recovery rather than kill+new.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"

pmx_journal_has worker "WORKER-START" \
  || pmx_fail "'worker' journal missing WORKER-START — wrong terminal?"

pmx_journal_has worker "WORKER-RECOVERED" \
  || pmx_fail "'worker' never ran the recovery command — the hung command was not cleared in place"

pmx_runner_trace_proves S09 \
  || pmx_fail "runner-owned proxy trace does not prove C-c preceded recovery on worker"

pmx_pass "interrupted the hung command and recovered the same terminal"
