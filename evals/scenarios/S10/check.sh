#!/usr/bin/env bash
# S10 check. Pass = the agent read the note (only there could it learn the token) and carried out its
# instruction: token.txt now contains ZT-9QK.
set -uo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "$SCEN_DIR/env.sh"

pmx_index_has handoff "ZT-9QK" \
  || pmx_fail "the note was never present on 'handoff' (setup problem?)"

[ -f "$SCEN_DIR/token.txt" ] \
  || pmx_fail "token.txt was not created — the agent did not act on the note"

grep -qF "ZT-9QK" "$SCEN_DIR/token.txt" \
  || pmx_fail "token.txt does not contain the token from the note (agent did not read the note)"

pmx_pass "read the human's note and carried out its instruction"
