#!/usr/bin/env bash
# S10 — note relay: a human left an instruction as a note; the agent must read it and act on it.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s10
rm -f "$SCEN_DIR/token.txt"

# Create the terminal and leave the human's message on it.
"$(pmx_bin)" --json new --name handoff >/dev/null
"$(pmx_bin)" --json note handoff \
  "The staging deploy token is ZT-9QK. Please write exactly that token into a file named token.txt in the working directory." >/dev/null
echo "S10 ready. Terminal 'handoff' has a note waiting."
