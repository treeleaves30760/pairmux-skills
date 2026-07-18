#!/usr/bin/env bash
# S06 check. Pass = the REPL evaluated the expression (result 7006652 appears in a journal).
set -uo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "$SCEN_DIR/env.sh"
TRANSCRIPT="${1:-}"

pmx_any_journal_has "7006652" \
  || pmx_fail "the REPL result 7006652 was not produced (did the agent drive the live REPL?)"

pmx_transcript_forbids "$TRANSCRIPT" '(^|[^[:alnum:]_])sleep[[:space:]]+[0-9]' \
  || pmx_fail "transcript used a fixed sleep instead of peeking for the REPL output"

pmx_pass "drove the Python REPL and read back the result"
