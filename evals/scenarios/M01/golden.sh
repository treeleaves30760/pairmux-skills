#!/usr/bin/env bash
# M01 control-plane reference + stdlib regressions. Never copied to agents.
# --harness {pmx-cli,rawtmux,shell}; shell uses only available host tmux.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"

if [ "${1:-}" = "--self-test" ]; then
  exec python3 -I - "$SCRIPT_DIR" <<'PY'
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

source = Path(sys.argv[1])

class ProtocolTests(unittest.TestCase):
    def run_check(self, root, env, passes):
        check = subprocess.run([str(root / "check.sh")], cwd=root, env=env, capture_output=True, text=True, timeout=30)
        ledger_path = Path(env.get("PAIRMUX_EVAL_SUBGOALS_FILE", str(root / "subgoals.json")))
        ledger = json.loads(ledger_path.read_text())
        self.assertEqual(ledger["schema"], "pairmux.eval.subgoals.v1")
        self.assertEqual(len(ledger["subgoals"]), 5)
        actual = {e["id"] for e in ledger["subgoals"] if e["pass"]}
        self.assertEqual(actual, passes, check.stdout + check.stderr)
        self.assertEqual(check.returncode == 0, len(passes) == 5)
        self.assertTrue(all(e["detail"].startswith(("capability:", "admin:")) for e in ledger["subgoals"]))

    def test_harness_neutral_golden_and_tampering(self):
        all_ids = {"server_answered", "tests_completed", "fatal_exact", "server_stopped", "done_marker"}
        for harness, scale in (("pmx-cli", "0.02"), ("rawtmux", "0.15"), ("shell", "0.02"),
                               ("shell-suite-first", "0.02")):
            with self.subTest(harness=harness), tempfile.TemporaryDirectory(prefix="pmx-m01-test-", dir="/tmp") as tmp:
                root = Path(tmp) / "evals/scenarios/M01"
                shutil.copytree(source, root, ignore=shutil.ignore_patterns("__pycache__", "state", "env.sh", "subgoals.json"))
                shutil.copy2(source.parents[1] / "lib.sh", root.parents[1] / "lib.sh")
                env = os.environ.copy()
                for key in list(env):
                    if key.startswith("PAIRMUX_EVAL_"):
                        del env[key]
                env.update(EVAL_TIME_SCALE=scale, PAIRMUX_EVAL_SOCKET="pmx-m01-" + Path(tmp).name[-6:])
                subprocess.run([str(root / "setup.sh")], cwd=root, env=env, check=True, capture_output=True, timeout=30)
                try:
                    self.run_check(root, env, set())
                    subprocess.run([str(root / "golden.sh"), "--harness", harness], cwd=root, env=env,
                                   check=True, capture_output=True, text=True, timeout=90)
                    self.run_check(root, env, all_ids)
                    if harness != "pmx-cli":
                        continue
                    for filename, subgoal in (("answer-server.txt", "server_answered"),
                                               ("answer-tests.txt", "tests_completed"),
                                               ("answer-fatal.txt", "fatal_exact"), ("DONE.txt", "done_marker")):
                        saved = (root / filename).read_bytes()
                        (root / filename).write_bytes(saved + b"extra\n")
                        self.run_check(root, env, all_ids - {subgoal})
                        (root / filename).write_bytes(saved)
                    events = root / "m01-events.jsonl"
                    original = events.read_bytes()
                    entries = [json.loads(line) for line in original.splitlines()]
                    for event in ("listener_approved", "fatal_reviewed", "suite_batch", "suite_resumed", "server_stopped", "status_requested"):
                        altered = [dict(e) for e in entries if e["event"] != event]
                        for seq, e in enumerate(altered, 1):
                            e["seq"] = seq
                        events.write_text("".join(json.dumps(e) + "\n" for e in altered))
                        self.run_check(root, env, {"done_marker"})
                        events.write_bytes(original)
                    for event, field, value in (("server_stopped", "reason", "watchdog"),
                                                 ("server_stopped", "instance", "replacement"),
                                                 ("suite_batch", "digest", "fabricated")):
                        altered = [dict(e) for e in entries]
                        next(e for e in altered if e["event"] == event)[field] = value
                        events.write_text("".join(json.dumps(e) + "\n" for e in altered))
                        self.run_check(root, env, {"done_marker"})
                        events.write_bytes(original)
                    # Serial/lifecycle tamper: readiness before any test work.
                    altered = [dict(e) for e in entries]
                    ready = next(e for e in altered if e["event"] == "server_ready")
                    altered.remove(ready)
                    altered.insert(1, ready)
                    for seq, e in enumerate(altered, 1):
                        e["seq"], e["at_ns"] = seq, seq
                    events.write_text("".join(json.dumps(e) + "\n" for e in altered))
                    self.run_check(root, env, {"done_marker"})
                    events.write_bytes(original)
                    self.run_check(root, env, all_ids)
                    for name in ("bigserver.py", "slowtests.sh", "noisy.log"):
                        artifact = root / name
                        saved = artifact.read_bytes()
                        artifact.write_bytes(saved + b"# tampered\n")
                        self.run_check(root, env, {"done_marker"})
                        artifact.write_bytes(saved)
                    for event, field, value in (("server_started", "fatal_present", True),
                                                 ("suite_started", "fatal_present", True)):
                        altered = [dict(e) for e in entries]
                        next(e for e in altered if e["event"] == event)[field] = value
                        events.write_text("".join(json.dumps(e) + "\n" for e in altered))
                        self.run_check(root, env, {"done_marker"})
                        events.write_bytes(original)
                    # Same checks under runner work/control isolation: no golden,
                    # checker or env file is offered inside the agent worktree.
                    isolated = Path(tmp) / "isolated/evals/scenarios/M01"
                    isolated.mkdir(parents=True)
                    for name in ("check.sh", "setup.sh", "golden.sh"):
                        shutil.copy2(root / name, isolated / name)
                    shutil.copy2(root.parents[1] / "lib.sh", isolated.parents[1] / "lib.sh")
                    isolated_env = Path(tmp) / "isolated/env.sh"
                    shutil.move(str(root / "env.sh"), isolated_env)
                    for name in ("check.sh", "setup.sh", "golden.sh"):
                        (root / name).unlink()
                    env.update(PAIRMUX_EVAL_SCENARIO_DIR=str(root), PAIRMUX_EVAL_ENV_FILE=str(isolated_env),
                               PAIRMUX_EVAL_SUBGOALS_FILE=str(root / "subgoals.json"))
                    self.run_check(isolated, env, all_ids)
                finally:
                    subprocess.run(["tmux", "-L", env["PAIRMUX_EVAL_SOCKET"], "kill-server"], capture_output=True)

unittest.main(argv=["m01-protocol"], verbosity=2)
PY
fi

harness="pmx-cli"
if [ "${1:-}" = "--harness" ]; then harness="${2:?harness}"; fi
case "$harness" in pmx-cli|rawtmux|shell|shell-suite-first) ;; *) exit 2 ;; esac
# shellcheck source=/dev/null
. "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}"
# Control-plane only: do not load the host's shell startup files or global CLI
# settings during infrastructure goldens. No host files/binaries are modified.
golden_home="$(mktemp -d /tmp/pmx-m01-home-XXXXXX)"
SHELL="$(command -v zsh)"
export HOME="$golden_home" ZDOTDIR="$golden_home" SHELL
printf 'export PATH=%q\n' "$PATH" >"$golden_home/.zshenv"
cd "$SCEN_DIR"

wait_event() {
  python3 -I - "$SCEN_DIR/m01-events.jsonl" "$1" <<'PY'
import json
from pathlib import Path
import sys
import time
p, event = Path(sys.argv[1]), sys.argv[2]
deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    try:
        if any(json.loads(line).get("event") == event for line in p.read_text().splitlines()):
            raise SystemExit(0)
    except (OSError, json.JSONDecodeError):
        pass
    time.sleep(0.05)
raise SystemExit("golden: missing logical event " + event)
PY
}
cleanup() {
  tmux -L "$PAIRMUX_SOCKET" kill-server >/dev/null 2>&1 || true
  rm -rf "$golden_home"
}
trap cleanup EXIT

if [ "$harness" = "pmx-cli" ]; then
  pairmux new --name m01server --cwd "$SCEN_DIR" --cmd "python3 -I bigserver.py"
  pairmux new --name m01tests --cwd "$SCEN_DIR"
  pairmux run m01tests "./slowtests.sh" --timeout 1s
  pairmux new --name m01work --cwd "$SCEN_DIR"
elif [ "$harness" = "shell-suite-first" ]; then
  # Tests-first startup must be equally valid, even on a very fast machine.
  tmux -L "$PAIRMUX_SOCKET" new-session -d -s m01 -n tests -c "$SCEN_DIR" "./slowtests.sh"
  wait_event suite_started
  tmux -L "$PAIRMUX_SOCKET" new-window -t m01 -n server -c "$SCEN_DIR" "python3 -I bigserver.py"
else
  tmux -L "$PAIRMUX_SOCKET" new-session -d -s m01 -n server -c "$SCEN_DIR" "python3 -I bigserver.py"
  tmux -L "$PAIRMUX_SOCKET" new-window -t m01 -n tests -c "$SCEN_DIR" "./slowtests.sh"
fi
wait_event listener_prompt
if [ "$harness" = "pmx-cli" ]; then
  pairmux run m01work "grep -F FATAL noisy.log > answer-fatal.txt"
  pairmux send m01server --text y --enter
else
  grep -F FATAL noisy.log >answer-fatal.txt
  tmux -L "$PAIRMUX_SOCKET" send-keys -t m01:server -l y
  tmux -L "$PAIRMUX_SOCKET" send-keys -t m01:server Enter
fi
wait_event server_ready
port="$(tr -d '\n' <server-port.txt)"
curl --fail --silent --show-error --max-time 10 "http://127.0.0.1:$port/status" >answer-server.txt
wait_event suite_completed
cp test-report.txt answer-tests.txt
if [ "$harness" = "pmx-cli" ]; then
  pairmux send m01server --key C-c
else
  tmux -L "$PAIRMUX_SOCKET" send-keys -t m01:server C-c
fi
wait_event server_stopped
printf 'all three complete\n' >DONE.txt
