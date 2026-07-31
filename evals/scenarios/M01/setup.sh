#!/usr/bin/env bash
# M01 — triage board: three concurrent jobs (server boot, test suite, log dig).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" m01
chmod +x "$SCEN_DIR/bigserver.py" "$SCEN_DIR/slowtests.sh"
rm -f "$SCEN_DIR"/answer-*.txt "$SCEN_DIR/server-port.txt" "$SCEN_DIR/test-report.txt" \
  "$SCEN_DIR/DONE.txt" "$SCEN_DIR/subgoals.json" "$SCEN_DIR/noisy.log"
command -v python3 >/dev/null 2>&1 || echo "warning: python3 not on PATH; this scenario needs it." >&2
command -v curl    >/dev/null 2>&1 || echo "warning: curl not on PATH; this scenario needs it." >&2

# Deterministic 10k-line log with exactly one FATAL line buried at line 6437.
python3 - "$SCEN_DIR/noisy.log" <<'PY'
import sys

FATAL = "2026-08-01T03:14:07Z FATAL: disk quota exceeded on shard-17 token=FT-55d1"
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    for i in range(1, 10001):
        if i == 6437:
            handle.write(FATAL + "\n")
        else:
            handle.write(f"2026-08-01T03:{(i // 300) % 60:02d}:{i % 60:02d}Z INFO worker-{i % 7} heartbeat seq={i}\n")
PY
echo "M01 ready. Jobs: bigserver.py (slow boot), slowtests.sh (~20s), noisy.log (10k lines)."
