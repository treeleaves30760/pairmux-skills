#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" m06
rm -f "$SCEN_DIR"/{queue.jsonl,checkpoint.json,priority.txt,human-note.txt,release.txt,tests.txt,docs.txt,subgoals.json}
mkdir -p "$PAIRMUX_STATE_DIR/m06-human"
printf 'revision=initial\norder=docs,tests,release\n' >"$SCEN_DIR/priority.txt"
chmod +x "$SCEN_DIR/queue.py"
nohup "$SCRIPT_DIR/human.sh" "$SCEN_DIR" "$PAIRMUX_STATE_DIR/m06-human" \
  >"$PAIRMUX_STATE_DIR/m06-human/human.log" 2>&1 &
printf '%s\n' "$!" >"$PAIRMUX_STATE_DIR/m06-human/human.pid"
printf 'M06 ready: initial docs/tests/release queue; a human will revise it at the live checkpoint.\n'
