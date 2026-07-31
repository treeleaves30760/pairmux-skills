#!/usr/bin/env bash
# M03 golden path — reference pairmux solution: start the migration, summon
# the human at the prompt, keep the sideworks moving during the handoff, and
# resume on the human's note. Control-plane only.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"

cd "$SCEN_DIR"

# Start the migration; it will stop at the password prompt.
pairmux new --name m03mig --cwd "$SCEN_DIR"
pairmux run m03mig "./fake-sudo-migrate.sh" --timeout 8s || true

# Summon the human to the live pairmux terminal, then keep working.
printf '{"channel": "pairmux", "terminal": "m03mig"}\n' >handoff.json

pairmux new --name m03side --cwd "$SCEN_DIR"
pairmux run m03side "./sidework-a.sh && ./sidework-b.sh" --timeout 300s

# The human answers while the sideworks run; collect their note and let the
# migration settle.
pairmux wait m03mig --human --timeout 240s
pairmux wait m03mig --idle 800 --timeout 60s
[ -f migration-done.txt ] || { echo "golden: migration did not commit" >&2; exit 1; }

pairmux run m03side "printf 'migration complete\n' > DONE.txt"
pairmux kill --all
