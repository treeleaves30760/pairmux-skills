#!/usr/bin/env bash
# S07 — a terminal left stuck in a pager. The agent must recognise it and escape with q.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s07

# Create a terminal and leave it parked inside `less` (awaiting-input at a pager prompt).
command -v less >/dev/null 2>&1 || {
  echo "error: S07 requires less" >&2
  exit 1
}
"$(pmx_bin)" --json new --name report >/dev/null
"$(pmx_bin)" --json run report "seq 500 | less" --timeout 3s >/dev/null
pmx_status_is report awaiting-input || {
  echo "error: S07 setup did not leave report at a pager prompt" >&2
  exit 1
}
echo "S07 ready. Terminal 'report' is stuck in a pager."
