#!/usr/bin/env bash
# Private reference solution: all interactions go through a real pairmux PTY.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
pmx() { "$PAIRMUX_BIN" "$@"; }
pmx new --name m02chain --cwd "$SCEN_DIR"
pmx run m02chain "python3 flow.py repl" --timeout 2s
pmx send m02chain --text '1234 * 5678' --enter
pmx wait m02chain --idle 150 --timeout 15s
value="$(pmx --json peek m02chain | python3 -I -c '
import json, re, sys
output = json.load(sys.stdin)["output"]
values = re.findall(r"(?m)^([0-9]+)\r?$", output)
assert values, output
print(values[-1])
')"
printf '%s\n' "$value" >"$SCEN_DIR/answer-value.txt"
pmx send m02chain --text 'exit()' --enter
pmx wait m02chain --idle 150 --timeout 15s
pmx run m02chain "python3 flow.py deploy $value" --timeout 2s
pmx send m02chain --text Y --enter
pmx wait m02chain --idle 150 --timeout 15s
pmx --json peek m02chain | python3 -I -c 'import json, sys; assert "(END)" in json.load(sys.stdin)["output"]'
pmx send m02chain --text q
pmx wait m02chain --idle 150 --timeout 15s
pmx kill --all
