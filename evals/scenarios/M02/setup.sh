#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" m02
rm -f "$SCEN_DIR"/{interaction.jsonl,deployment.txt,answer-value.txt,subgoals.json}
chmod +x "$SCEN_DIR/flow.py"
printf 'M02 ready: a live calculation, a deployment confirmation, and an embedded pager.\n'
