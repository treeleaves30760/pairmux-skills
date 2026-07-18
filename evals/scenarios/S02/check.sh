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

# The whole point of S02: no fixed sleeps to guess when the build is done. Scoped to agent-ISSUED
# content (see lib.sh): the fixture slow-build.sh contains `sleep 0.25`, so a prudent pre-execution
# Read of it echoes that into a tool_result — a fixture artifact, not the agent sleeping.
pmx_issued_forbids "$TRANSCRIPT" '(^|[^[:alnum:]_])sleep[[:space:]]+[0-9]' \
  || pmx_fail "transcript used a fixed 'sleep N' to guess build timing — use run/wait instead"

pmx_pass "slow build completed and the agent waited without sleep-guessing"
