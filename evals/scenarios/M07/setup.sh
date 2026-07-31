#!/usr/bin/env bash
# M07 — long non-interactive build (the honest control scenario: every harness
# should complete it; the interesting data is the efficiency metrics).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" m07
chmod +x "$SCEN_DIR/bigbuild.sh"
rm -f "$SCEN_DIR/build-out.txt" "$SCEN_DIR/answer-build.txt" "$SCEN_DIR/subgoals.json"
echo "M07 ready. bigbuild.sh is a plain long build."
