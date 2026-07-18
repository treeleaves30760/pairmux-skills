#!/usr/bin/env bash
# S08 — background server + client + log grep across two terminals.
set -euo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
pmx_setup "$SCEN_DIR" s08
chmod +x "$SCEN_DIR/server.sh" "$SCEN_DIR/hit.sh"
rm -f "$SCEN_DIR/port.txt"
command -v python3 >/dev/null 2>&1 || echo "warning: python3 not on PATH; this scenario needs it." >&2
command -v curl    >/dev/null 2>&1 || echo "warning: curl not on PATH; this scenario needs it." >&2
echo "S08 ready. server.sh starts a background server; hit.sh sends one request."
