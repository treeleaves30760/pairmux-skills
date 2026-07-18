#!/usr/bin/env bash
# S09 — a terminal stuck on a hung command. The agent must interrupt it and reuse the SAME terminal.
set -euo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s09

# Start a command that prints a marker and then hangs effectively forever.
"$(pmx_bin)" --json new --name worker >/dev/null
"$(pmx_bin)" --json run worker "echo WORKER-START; sleep 600" --timeout 3s >/dev/null || true
echo "S09 ready. Terminal 'worker' is hung on a long sleep after printing WORKER-START."
