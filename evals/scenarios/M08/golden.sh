#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
pmx() { "$PAIRMUX_BIN" "$@"; }
pmx new --name m08server --cwd "$SCEN_DIR"
pmx run m08server 'python3 server.py' --timeout 100ms
# Readiness may precede a future-only pattern wait at scaled timing. Observe the
# returned/current output first, then arm a wait only if the event is still ahead.
if ! pmx --json peek m08server | python3 -I -c 'import json, sys; sys.exit(0 if "READY http" in json.load(sys.stdin)["output"] else 1)'; then
  pmx wait m08server --pattern 'READY http' --timeout 15s
fi
pmx --json peek m08server | python3 -I -c 'import json, sys; assert "READY http" in json.load(sys.stdin)["output"]'
pmx new --name m08client --cwd "$SCEN_DIR"
# Expansion belongs to the live client shell, not this private driver.
# shellcheck disable=SC2016
pmx run m08client 'curl --fail --silent --show-error "http://127.0.0.1:$(cat server-port.txt)/status" > answer-server.txt' --timeout 15s
pmx --json log m08server --grep '^REQUEST receipt=' | python3 -I -c '
import json, pathlib, re, sys
output = json.load(sys.stdin)["output"]
lines = [re.sub(r"^[0-9]+:", "", line) for line in output.splitlines()]
lines = [line for line in lines if line.startswith("REQUEST receipt=")]
assert len(lines) == 1, output
pathlib.Path(sys.argv[1]).write_text(lines[0] + "\n")
' "$SCEN_DIR/answer-request.txt"
pmx send m08server --key C-c
pmx wait m08server --done --timeout 15s
pmx kill --all
