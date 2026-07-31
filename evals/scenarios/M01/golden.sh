#!/usr/bin/env bash
# M01 golden path — reference pairmux solution used by evals/test-scenarios.sh
# to prove the fixtures and check.sh agree. Deterministic over showy: the
# pattern wait is armed immediately after the server terminal is created
# (pattern waits observe future output only), and the remaining jobs run
# sequentially. Control-plane only; agents never see this file.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"

cd "$SCEN_DIR"

# Server as a program terminal; arm the readiness wait right away.
pairmux new --name m01server --cwd "$SCEN_DIR" --cmd "python3 bigserver.py"
pairmux wait m01server --pattern "LISTENING on" --timeout 120s

pairmux new --name m01work --cwd "$SCEN_DIR"
pairmux run m01work "curl -s \"http://127.0.0.1:\$(cat server-port.txt)/status\" > answer-server.txt" --timeout 30s
pairmux run m01work "grep -F FATAL noisy.log > answer-fatal.txt" --timeout 30s
pairmux run m01work "./slowtests.sh > /dev/null" --timeout 180s
pairmux run m01work "tail -1 test-report.txt > answer-tests.txt"

# Shut the server down cleanly, then finish up.
pairmux send m01server --key C-c
pairmux wait m01server --idle 500 --timeout 30s || true
pairmux run m01work "printf 'all three complete\n' > DONE.txt"
pairmux kill --all
