#!/usr/bin/env bash
# S03 check. Pass = the file was displayed through pairmux AND the agent reported the FATAL code.
set -uo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "$SCEN_DIR/env.sh"
TRANSCRIPT="${1:-}"

# The agent must have run the display through pairmux (the 10k lines land in the journal).
pmx_any_journal_has "code E4231" \
  || pmx_fail "haystack was never displayed through pairmux (E4231 not in any journal)"

# And it must have reported the specific error code it could only get by querying the journal.
pmx_transcript_requires "$TRANSCRIPT" 'E4231' \
  || pmx_fail "agent did not report the FATAL error code E4231"

pmx_pass "found and reported the buried FATAL line"
