#!/usr/bin/env bash
# S01 check. Pass = some terminal printed PAIRMUX-S01-OK via pairmux. Optional $1 = transcript file.
set -uo pipefail
SCEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCEN_DIR/../../lib.sh"
# shellcheck source=/dev/null
. "$SCEN_DIR/env.sh"
TRANSCRIPT="${1:-}"

pmx_any_journal_has "PAIRMUX-S01-OK" \
  || pmx_fail "expected marker PAIRMUX-S01-OK not found in any terminal journal (did the agent run it via pairmux?)"

# Basic loop should not sleep-and-guess for an instant command.
pmx_transcript_forbids "$TRANSCRIPT" '(^|[^[:alnum:]_])sleep[[:space:]]+[0-9]' \
  || pmx_fail "transcript used a fixed sleep to guess timing"

pmx_pass "instant command ran and completed via pairmux"
