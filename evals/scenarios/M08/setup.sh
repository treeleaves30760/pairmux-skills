#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" m08
rm -f "$SCEN_DIR"/{server-events.jsonl,server-port.txt,server.pid,requests.log,answer-server.txt,answer-request.txt,subgoals.json}
chmod +x "$SCEN_DIR/server.py"
command -v curl >/dev/null
printf 'M08 ready: a slow localhost-only stdlib server with exact request readback.\n'
