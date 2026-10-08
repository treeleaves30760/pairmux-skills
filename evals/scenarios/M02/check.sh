#!/usr/bin/env bash
# Only fixture evidence, never a pairmux-specific journal.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"
verdicts="$(python3 -I - "$SCEN_DIR" <<'PY'
import ast
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
try:
    rows = [json.loads(line) for line in (root / 'interaction.jsonl').read_text().splitlines()]
except (OSError, ValueError):
    rows = []

def one(event):
    matches = [row for row in rows if row.get('event') == event]
    return matches[0] if len(matches) == 1 else {}

def text(name):
    try:
        return (root / name).read_text().strip()
    except OSError:
        return ''

def ordered(*events):
    stamps = [one(event).get('time_ns', 0) for event in events]
    return all(a > 0 and a < b for a, b in zip(stamps, stamps[1:]))

valid = bool(rows) and all(isinstance(row.get('pid'), int) and row['pid'] > 1
                          and isinstance(row.get('ppid'), int) and row['ppid'] > 1
                          and isinstance(row.get('sid'), int) and row['sid'] > 1
                          and str(row.get('tty', '')).startswith('/dev/')
                          and row.get('cwd') == str(root) for row in rows)
valid = valid and len({(row['ppid'], row['sid'], row['tty'], row['cwd']) for row in rows}) == 1
start, result, end = (one(event) for event in ('repl_started', 'repl_result', 'repl_exited'))
deploy, confirmation, pager, quit_, done = (one(event) for event in
    ('deploy_started', 'confirmation', 'pager_entered', 'pager_exit', 'deployment_complete'))
inputs = [row for row in rows if row.get('event') == 'repl_input']
values, displays = {}, []

def integer(node):
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value, False
    if isinstance(node, ast.Name):
        return values.get(node.id, (None, False))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left, right = integer(node.left), integer(node.right)
        if left[0] is not None and right[0] is not None:
            return left[0] * right[0], left[1] or right[1] or sorted((left[0], right[0])) == [1234, 5678]
    return None, False

# AST-only data flow: never execute transcript input in the trusted checker.
# Only a product-derived displayed value counts, not a multiplication buried in
# an uncalled function or discarded before printing a canned constant.
for row in inputs:
    try:
        tree = ast.parse(row['source'], mode='exec')
        for statement in tree.body:
            if isinstance(statement, ast.Assign):
                value = integer(statement.value)
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        values[target.id] = value
            elif isinstance(statement, ast.Expr):
                node = statement.value
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print':
                    node = node.args[0] if len(node.args) == 1 and not node.keywords else None
                value = integer(node)
                if value[0] is not None:
                    displays.append((row.get('time_ns', 0), value))
    except (SyntaxError, KeyError):
        pass
result_displays = [value for stamp, value in displays if stamp < result.get('time_ns', 0)]
computed = bool(result_displays) and result_displays[-1] == (7006652, True)
repl_ok = valid and computed and result.get('value') == 7006652 and start.get('pid') == result.get('pid') == end.get('pid')
repl_ok = repl_ok and ordered('repl_started', 'repl_result', 'repl_exited')
repl_ok = repl_ok and start.get('pid') != deploy.get('pid') and all(row.get('pid') == start.get('pid') for row in inputs)
propagated = repl_ok and all(row.get('value') == result.get('value') for row in (deploy, confirmation, pager, quit_, done))
propagated = propagated and text('answer-value.txt') == str(result.get('value'))
propagated = propagated and all(start.get(key) == deploy.get(key) for key in ('ppid', 'sid', 'tty', 'cwd'))
propagated = propagated and ordered('repl_exited', 'deploy_started')
confirmed = valid and confirmation.get('answer') in ('Y', 'y') and confirmation.get('pid') == deploy.get('pid')
confirmed = confirmed and ordered('deploy_started', 'confirmation', 'pager_entered')
keys = [row for row in rows if row.get('event') == 'pager_key']
escaped = valid and len(keys) == 1 and keys[0].get('key') == 'q' and keys[0].get('pid') == quit_.get('pid')
escaped = escaped and all(row.get('pid') == deploy.get('pid') for row in (pager, quit_, done))
escaped = escaped and ordered('pager_entered', 'pager_key', 'pager_exit', 'deployment_complete')
complete = propagated and confirmed and escaped and done.get('pid') == deploy.get('pid') == pager.get('pid')
complete = complete and done.get('value') == 7006652 and text('deployment.txt') == 'DEPLOYED release=7006652'
for verdict in (repl_ok, propagated, confirmed, escaped, complete):
    print(int(bool(verdict)))
PY
)"
IFS=$'\n' read -r -d '' -a flags < <(printf '%s\n' "$verdicts") || true
pmx_subgoal repl_live_result "${flags[0]:-0}" 'capability: a real terminal REPL displayed the computed result and exited'
pmx_subgoal value_propagated "${flags[1]:-0}" 'capability: that result reached deployment in the same terminal/session'
pmx_subgoal one_confirmation "${flags[2]:-0}" 'capability: exactly one affirmative deployment confirmation'
pmx_subgoal pager_exited "${flags[3]:-0}" 'capability: the live pager received q and exited normally'
pmx_subgoal deployment_complete "${flags[4]:-0}" 'capability: fixture deployment completed after the pager'
pmx_subgoals_finish
