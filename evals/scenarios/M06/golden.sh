#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
pmx() { "$PAIRMUX_BIN" "$@"; }
pmx new --name m06queue --cwd "$SCEN_DIR"
pmx run m06queue 'python3 queue.py checkpoint' --timeout 15s
pmx wait m06queue --idle 150 --timeout 15s
pmx --json peek m06queue | python3 -I -c 'import json, sys; assert "HUMAN NOTE" in json.load(sys.stdin)["output"]'
revision="$(python3 -I - "$SCEN_DIR/priority.txt" <<'PY'
import sys
print(dict(line.strip().split('=', 1) for line in open(sys.argv[1]))['revision'])
PY
)"
pmx run m06queue "python3 queue.py ack $revision"
for job in release tests docs; do
  pmx run m06queue "python3 queue.py work $job" --timeout 15s
done
pmx kill --all
