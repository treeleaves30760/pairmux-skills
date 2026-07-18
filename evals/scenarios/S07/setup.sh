#!/usr/bin/env bash
# S07 — a terminal left stuck in a pager. The agent must recognise it and escape with q.
set -euo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s07

# Create a terminal and leave it parked inside `less` (awaiting-input at a pager prompt).
"$(pmx_bin)" --json new --name report >/dev/null
"$(pmx_bin)" --json run report "seq 500 | less" --timeout 3s >/dev/null || true
echo "S07 ready. Terminal 'report' is stuck in a pager."
