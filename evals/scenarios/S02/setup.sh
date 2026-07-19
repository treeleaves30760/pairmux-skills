#!/usr/bin/env bash
# S02 — slow command (~20s fake build): must wait, never sleep-and-guess.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s02
chmod +x "$SCEN_DIR/slow-build.sh"
echo "S02 ready. slow-build.sh takes ~20s and prints BUILD COMPLETE."
