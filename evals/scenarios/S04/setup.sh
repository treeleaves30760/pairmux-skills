#!/usr/bin/env bash
# S04 — [y/N] confirmation: recognise awaiting-input and answer it once.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s04
chmod +x "$SCEN_DIR/confirm.sh"
echo "S04 ready. confirm.sh asks a [y/N] question."
