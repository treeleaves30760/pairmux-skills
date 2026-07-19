#!/usr/bin/env bash
# S08 check. Pass = the client got a 200 AND the server logged the request — proving two terminals
# cooperated (server running in one, request driven from another, journal read back).
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
TRANSCRIPT="${1:-}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"

pmx_any_journal_has "HTTP-STATUS=200" \
  || pmx_fail "the client never got a 200 from the server (hit.sh did not succeed)"

pmx_any_journal_has '"GET / HTTP/1.1" 200' \
  || pmx_fail "the server never logged the request (was the server actually running in a terminal?)"

pmx_runner_trace_proves S08 \
  || pmx_fail "runner-owned proxy trace does not prove distinct server/client terminals plus server journal readback"

pmx_issued_requires "$TRANSCRIPT" 'GET / HTTP/1[.]1.*200' \
  || pmx_fail "agent did not report the server's GET / HTTP/1.1 request line and 200 status"

pmx_pass "server + client cooperated across two terminals and the request was logged"
