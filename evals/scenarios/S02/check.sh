#!/usr/bin/env bash
# S02 check. Pass = the build ran to completion via pairmux AND the transcript did not sleep-and-guess.
set -uo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "$SCEN_DIR/env.sh"
TRANSCRIPT="${1:-}"

pmx_any_journal_has "BUILD COMPLETE" \
  || pmx_fail "build never reached completion (BUILD COMPLETE not in any journal)"

# The whole point of S02: no fixed sleeps to guess when the build is done.
# (The build fixture itself uses sleep internally, but that never appears in the agent's transcript.)
pmx_transcript_forbids "$TRANSCRIPT" '(^|[^[:alnum:]_])sleep[[:space:]]+[0-9]' \
  || pmx_fail "transcript used a fixed 'sleep N' to guess build timing — use run/wait instead"

pmx_pass "slow build completed and the agent waited without sleep-guessing"
