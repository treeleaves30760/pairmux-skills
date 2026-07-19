#!/usr/bin/env bash
# S10 check. Pass = the agent read the note (only there could it learn the token) and carried out its
# instruction: token.txt now contains ZT-9QK.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"

pmx_index_has handoff "ZT-9QK" \
  || pmx_fail "the note was never present on 'handoff' (setup problem?)"

[ -f "$SCEN_DIR/token.txt" ] \
  || pmx_fail "token.txt was not created — the agent did not act on the note"

printf 'ZT-9QK\n' | cmp -s - "$SCEN_DIR/token.txt" \
  || pmx_fail "token.txt must contain exactly the note token ZT-9QK and one newline"

pmx_runner_trace_proves S10 \
  || pmx_fail "runner-owned proxy trace does not prove the handoff note was read"

pmx_pass "read the human's note and carried out its instruction"
