#!/usr/bin/env bash
# S08 check. Pass = the client got a 200 AND the server logged the request — proving two terminals
# cooperated (server running in one, request driven from another, log read back).
set -uo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "$SCEN_DIR/env.sh"

pmx_any_journal_has "HTTP-STATUS=200" \
  || pmx_fail "the client never got a 200 from the server (hit.sh did not succeed)"

pmx_any_journal_has '"GET / HTTP/1.1" 200' \
  || pmx_fail "the server never logged the request (was the server actually running in a terminal?)"

pmx_pass "server + client cooperated across two terminals and the request was logged"
