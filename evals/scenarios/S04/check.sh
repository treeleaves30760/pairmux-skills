#!/usr/bin/env bash
# S04 check. Pass = the agent answered the prompt and the script proceeded (CONFIRMED, not ABORTED).
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
TRANSCRIPT="${1:-}"

pmx_any_journal_has "CONFIRMED-DELETING" \
  || pmx_fail "the confirmation was never answered 'yes' (CONFIRMED-DELETING absent)"

if pmx_any_journal_has "ABORTED"; then
  pmx_fail "the script aborted — the prompt was answered no/empty instead of yes"
fi

# Answering a prompt should not require sleeping to guess timing.
pmx_transcript_forbids "$TRANSCRIPT" '(^|[^[:alnum:]_])sleep[[:space:]]+[0-9]' \
  || pmx_fail "transcript used a fixed sleep instead of reacting to awaiting-input"

pmx_runner_trace_proves S04 \
  || pmx_fail "runner-owned proxy trace does not prove one yes answer on the prompt terminal"

pmx_pass "recognised the [y/N] prompt and answered it correctly"
