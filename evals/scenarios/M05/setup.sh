#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" m05
rm -f "$SCEN_DIR"/{jobs.jsonl,alpha.txt,beta.txt,recovery.txt,subgoals.json}
chmod +x "$SCEN_DIR/job.py"
printf 'M05 ready: two cooperative jobs and one interruptible hang.\n'
