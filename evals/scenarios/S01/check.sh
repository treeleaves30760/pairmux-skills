#!/usr/bin/env bash
# S01 check. Pass = some terminal printed PAIRMUX-S01-OK via pairmux. Optional $1 = transcript file.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
TRANSCRIPT="${1:-}"

pmx_any_journal_has "PAIRMUX-S01-OK" \
  || pmx_fail "expected marker PAIRMUX-S01-OK not found in any terminal journal (did the agent run it via pairmux?)"

# Basic loop should not sleep-and-guess for an instant command.
pmx_transcript_forbids "$TRANSCRIPT" '(^|[^[:alnum:]_])sleep[[:space:]]+[0-9]' \
  || pmx_fail "transcript used a fixed sleep to guess timing"

pmx_runner_trace_proves S01 \
  || pmx_fail "runner-owned proxy trace does not prove a successful S01 run"

pmx_issued_requires "$TRANSCRIPT" 'exit([[:space:]_-]*code)?[^0-9]*0|status[^[:alnum:]]*done' \
  || pmx_fail "agent did not report/confirm pairmux exit code 0"

pmx_pass "instant command ran and completed via pairmux"
