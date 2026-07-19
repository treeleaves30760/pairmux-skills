#!/usr/bin/env bash
# S03 — one error line buried in a huge log: truncation pointer -> log --grep.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s03

# Generate a 10,000-line haystack with exactly one FATAL line at a non-obvious position.
HAYSTACK="$SCEN_DIR/haystack.log"
awk 'BEGIN{
  for(i=1;i<=10000;i++){
    if(i==6137){ printf("FATAL: shard 7 checksum mismatch (code E4231)\n") }
    else { printf("INFO  line %05d ok — processing record %d\n", i, i*3) }
  }
}' > "$HAYSTACK"
echo "S03 ready. haystack.log has 10000 lines; exactly one contains FATAL / E4231."
