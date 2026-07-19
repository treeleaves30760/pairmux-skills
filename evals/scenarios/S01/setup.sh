#!/usr/bin/env bash
# S01 — instant command: the basic loop with no detours.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s01
echo "S01 ready. Isolated socket=$PAIRMUX_SOCKET state=$PAIRMUX_STATE_DIR"
