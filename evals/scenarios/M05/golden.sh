#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
pmx() { "$PAIRMUX_BIN" "$@"; }
for name in alpha beta hang; do
  pmx new --name "m05$name" --cwd "$SCEN_DIR"
  pmx run "m05$name" "python3 job.py $name" --timeout 200ms
done
# Fixture-internal logical subscriptions cover output that may precede a future
# pattern wait; the driver does not sleep or poll a terminal screen.
python3 -I - "$SCEN_DIR/jobs.jsonl" <<'PY'
import json, os, sys, time
from pathlib import Path
path = Path(sys.argv[1])
deadline = time.monotonic() + 15
while True:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    ready = any(row['event'] == 'hung_ready' for row in rows)
    ready = ready and all(any(row['job'] == job and row['event'] == 'progress' for row in rows) for job in ('alpha', 'beta'))
    if ready:
        break
    assert time.monotonic() < deadline, rows
    time.sleep(0.2 * float(os.environ.get('EVAL_TIME_SCALE', '1')))
PY
pmx send m05hang --key C-c
pmx wait m05hang --idle 150 --timeout 15s
pmx run m05hang 'python3 job.py recover' --timeout 15s
pmx wait m05alpha --idle 150 --timeout 15s
pmx wait m05beta --idle 150 --timeout 15s
pmx kill --all
