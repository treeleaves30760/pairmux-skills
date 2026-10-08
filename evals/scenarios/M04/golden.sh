#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
pmx() { "$PAIRMUX_BIN" "$@"; }
pmx new --name m04a --cwd "$SCEN_DIR"
pmx new --name m04b --cwd "$SCEN_DIR"
pmx run m04a "cd a-work; source ../venv/bin/activate"
pmx run m04a 'export TOKEN=fixture-only-m04'
pmx run m04b 'unset TOKEN VIRTUAL_ENV; cd b-work'
pmx run m04a 'python ../identity.py A1'
pmx run m04b 'python3 ../identity.py B1'
pmx run m04a 'python ../identity.py A2'
pmx run m04b 'python3 ../identity.py B2'
pmx run m04a 'python ../identity.py A3'
pmx kill --all
