#!/usr/bin/env bash
# S09 — a terminal stuck on a hung command. The agent must interrupt it and reuse the SAME terminal.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s09

# Start a command that prints a marker and then hangs effectively forever.
"$(pmx_bin)" --json new --name worker >/dev/null
"$(pmx_bin)" --json run worker "echo WORKER-START; sleep 600" --timeout 3s >/dev/null
pmx_status_is worker running || {
  echo "error: S09 setup did not leave worker running" >&2
  exit 1
}
echo "S09 ready. Terminal 'worker' is hung on a long sleep after printing WORKER-START."
