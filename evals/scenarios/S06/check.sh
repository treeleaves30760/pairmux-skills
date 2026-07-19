#!/usr/bin/env bash
# S06 check. Pass = the REPL evaluated the expression (result 7006652 appears in a journal).
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
TRANSCRIPT="${1:-}"

pmx_any_journal_has "7006652" \
  || pmx_fail "the REPL result 7006652 was not produced (did the agent drive the live REPL?)"

pmx_transcript_forbids "$TRANSCRIPT" '(^|[^[:alnum:]_])sleep[[:space:]]+[0-9]' \
  || pmx_fail "transcript used a fixed sleep instead of peeking for the REPL output"

pmx_runner_trace_proves S06 \
  || pmx_fail "runner-owned proxy trace does not prove REPL evaluation plus clean exit"

pmx_any_journal_has ">>>" \
  || pmx_fail "Python REPL prompt was not observed in terminal state"

pmx_pass "drove the Python REPL, read back the result, and exited cleanly"
