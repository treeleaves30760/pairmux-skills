#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" m04
rm -f "$SCEN_DIR"/{identity.jsonl,environment.jsonl,a-first.txt,a-second.txt,a-third.txt,b-first.txt,b-second.txt,subgoals.json}
mkdir -p "$SCEN_DIR/a-work" "$SCEN_DIR/b-work"
python3 -I -m venv --without-pip "$SCEN_DIR/venv"
# Append the trusted source observer without replacing the stdlib activation.
# Keep source hashes in the private state; no agent-written evidence is trusted
# when either this observer or the real activation/interpreter fixture changed.
python3 -I - "$SCEN_DIR" "$PAIRMUX_STATE_DIR" <<'PY'
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import sys
root, state = (Path(arg).resolve() for arg in sys.argv[1:])
activation = root / 'venv' / 'bin' / 'activate'
# Stdlib exports intentionally precede our later wrapper definition.
activation.write_text('# shellcheck disable=SC2218\n' + activation.read_text())
with activation.open('a') as handle:
    handle.write('\n# M04 once-only source/export evidence\n')
    handle.write(f'_M04_ROOT={shlex.quote(str(root))}\n')
    handle.write(f'_M04_PYTHON={shlex.quote(shutil.which("python3"))}\n')
    handle.write(f'# shellcheck source={root}/observe-env.sh\n')
    handle.write('. "$_M04_ROOT/observe-env.sh"\n')
files = ('identity.py', 'observe-env.sh', 'venv/bin/activate')
(state / 'm04-fixture-hashes.json').write_text(json.dumps({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}) + '\n')
PY
chmod +x "$SCEN_DIR/identity.py"
printf 'M04 ready: stdlib venv, source/export observer, and independent work directories.\n'
