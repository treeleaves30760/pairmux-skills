#!/usr/bin/env bash
# S06 — Python REPL: drive an interactive interpreter with send/peek, not run.
set -euo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s06
command -v python3 >/dev/null 2>&1 || echo "warning: python3 not on PATH; this scenario needs it." >&2
echo "S06 ready."
