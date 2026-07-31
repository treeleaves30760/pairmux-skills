#!/usr/bin/env bash
# M07 golden path — reference pairmux solution used by evals/test-scenarios.sh
# to prove the fixtures and check.sh agree. Not visible to agents.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"

cd "$SCEN_DIR"
pairmux new --name m07build --cwd "$SCEN_DIR"
pairmux run m07build "./bigbuild.sh" --timeout 180s
pairmux run m07build "tail -1 build-out.txt > answer-build.txt"
pairmux kill m07build
