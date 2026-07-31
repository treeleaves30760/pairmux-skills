#!/usr/bin/env bash
# Infrastructure self-test for the M suite — zero model cost.
#
# For each scenario (default: every M*), in an isolated copy:
#   1. negative: setup, then check.sh on the untouched fixture MUST fail;
#   2. golden:   setup, run golden.sh (the reference pairmux solution), then
#                check.sh MUST pass with every subgoal green.
# EVAL_TIME_SCALE shrinks fixture sleeps (default 0.15 here; real runs use 1).
set -euo pipefail
EVALS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export EVAL_TIME_SCALE="${EVAL_TIME_SCALE:-0.15}"

if [ "$#" -gt 0 ]; then
  scenarios=("$@")
else
  scenarios=()
  for dir in "$EVALS_DIR"/scenarios/M[0-9]*; do
    [ -d "$dir" ] && scenarios+=("$(basename "$dir")")
  done
fi
[ "${#scenarios[@]}" -gt 0 ] || { echo "no M scenarios found" >&2; exit 1; }

if [ -z "${PAIRMUX_REAL_BIN:-}" ]; then
  sibling="$EVALS_DIR/../../pairmux/bin/pairmux"
  if [ -x "$sibling" ]; then
    PAIRMUX_REAL_BIN="$(cd "$(dirname "$sibling")" && pwd)/pairmux"
    export PAIRMUX_REAL_BIN
  fi
fi

failures=0
for scen in "${scenarios[@]}"; do
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/pmx-scen-test-XXXXXX")"
  root="$tmp/evals"
  mkdir -p "$root/scenarios"
  cp "$EVALS_DIR/lib.sh" "$root/lib.sh"
  cp -R "$EVALS_DIR/scenarios/$scen" "$root/scenarios/$scen"
  scendir="$root/scenarios/$scen"

  cleanup_scenario() {
    if [ -f "$scendir/env.sh" ]; then
      # shellcheck source=/dev/null
      sock="$(. "$scendir/env.sh" >/dev/null 2>&1; printf '%s' "${PAIRMUX_SOCKET:-}")"
      [ -n "$sock" ] && tmux -L "$sock" kill-server >/dev/null 2>&1 || true
    fi
    if [ -f "$scendir/.mig-config" ]; then
      # shellcheck source=/dev/null
      mig="$(. "$scendir/.mig-config" >/dev/null 2>&1; printf '%s' "${MIG_TMP:-}")"
      if [ -n "$mig" ] && [ -d "$mig" ]; then
        [ -f "$mig/human.pid" ] && kill "$(cat "$mig/human.pid")" 2>/dev/null || true
        rm -rf "$mig"
      fi
    fi
  }

  echo "== $scen: negative (untouched fixture must fail check) =="
  (cd "$scendir" && ./setup.sh >setup.log 2>&1)
  if (cd "$scendir" && ./check.sh >check-negative.log 2>&1); then
    echo "FAIL [$scen] check.sh passed on an untouched fixture" >&2
    sed 's/^/    /' "$scendir/check-negative.log" >&2 || true
    failures=$((failures + 1))
    cleanup_scenario
    continue
  fi
  cleanup_scenario

  echo "== $scen: golden (reference solution must pass check) =="
  (cd "$scendir" && ./setup.sh >setup.log 2>&1)
  if ! (cd "$scendir" && ./golden.sh >golden.log 2>&1); then
    echo "FAIL [$scen] golden.sh errored" >&2
    tail -40 "$scendir/golden.log" | sed 's/^/    /' >&2 || true
    failures=$((failures + 1))
    cleanup_scenario
    continue
  fi
  if ! (cd "$scendir" && ./check.sh >check-golden.log 2>&1); then
    echo "FAIL [$scen] check.sh rejected the golden run" >&2
    sed 's/^/    /' "$scendir/check-golden.log" >&2 || true
    failures=$((failures + 1))
    cleanup_scenario
    continue
  fi
  grep '^score:' "$scendir/check-golden.log" | sed "s/^/   $scen golden /" || true
  cleanup_scenario
  rm -rf "$tmp"
  echo "OK $scen"
done

if [ "$failures" -gt 0 ]; then
  echo "test-scenarios: $failures scenario(s) failed" >&2
  exit 1
fi
echo "test-scenarios: all ${#scenarios[@]} scenario(s) validated"
