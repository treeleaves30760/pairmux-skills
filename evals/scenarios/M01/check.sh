#!/usr/bin/env bash
# M01 check — harness-agnostic artifacts only. Five subgoals, fractional score.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"

trimmed_first_line() {
  tr -d '\r' < "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | grep -v '^$' | head -1
}

ok=0
[ -f "$SCEN_DIR/answer-server.txt" ] && grep -qF "SERVER-OK-7f3a" "$SCEN_DIR/answer-server.txt" && ok=1
pmx_subgoal server_answered "$ok" "answer-server.txt must contain the /status response body"

ok=0
if [ -f "$SCEN_DIR/test-report.txt" ] && [ -f "$SCEN_DIR/answer-tests.txt" ] \
  && grep -qF "token=TP-9c2e" "$SCEN_DIR/test-report.txt" \
  && [ "$(trimmed_first_line "$SCEN_DIR/answer-tests.txt")" = "TESTS PASSED 42/42 token=TP-9c2e" ]; then
  ok=1
fi
pmx_subgoal tests_completed "$ok" "slowtests.sh must run to completion and answer-tests.txt must hold its exact final line"

ok=0
if [ -f "$SCEN_DIR/answer-fatal.txt" ] && [ -f "$SCEN_DIR/noisy.log" ]; then
  expected="$(grep -F 'FATAL' "$SCEN_DIR/noisy.log" | head -1)"
  [ -n "$expected" ] && [ "$(trimmed_first_line "$SCEN_DIR/answer-fatal.txt")" = "$expected" ] && ok=1
fi
pmx_subgoal fatal_exact "$ok" "answer-fatal.txt must hold the exact FATAL line from noisy.log"

ok=0
if [ -f "$SCEN_DIR/server-port.txt" ]; then
  port="$(tr -cd '0-9' < "$SCEN_DIR/server-port.txt")"
  if [ -n "$port" ] && python3 - "$port" <<'PY'
import socket
import sys

sock = socket.socket()
sock.settimeout(1.0)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(0)  # closed: shutdown succeeded
else:
    raise SystemExit(1)  # still listening
finally:
    sock.close()
PY
  then
    ok=1
  fi
fi
pmx_subgoal server_stopped "$ok" "the server must have started (server-port.txt) and no longer be listening"

ok=0
[ -f "$SCEN_DIR/DONE.txt" ] && [ "$(trimmed_first_line "$SCEN_DIR/DONE.txt")" = "all three complete" ] && ok=1
pmx_subgoal done_marker "$ok" "DONE.txt must contain exactly: all three complete"

pmx_subgoals_finish
