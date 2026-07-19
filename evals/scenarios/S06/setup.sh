#!/usr/bin/env bash
# S06 — Python REPL: drive an interactive interpreter with send/peek, not run.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s06
command -v python3 >/dev/null 2>&1 || echo "warning: python3 not on PATH; this scenario needs it." >&2
echo "S06 ready."
