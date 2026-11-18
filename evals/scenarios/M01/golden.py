#!/usr/bin/env python3
"""M01 control-plane reference + stdlib regressions. Never copied to agents.

    golden.py [--harness {pmx-cli,rawtmux,shell,shell-suite-first}]
    golden.py --self-test

pmx-cli runs on every platform. The rawtmux/shell baselines drive host tmux directly, so they are
POSIX-only; Windows has no tmux.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
HARNESSES = ("pmx-cli", "rawtmux", "shell", "shell-suite-first")
TMUX_HARNESSES = HARNESSES[1:]
FIXTURES = ("bigserver.py", evallib.fixture_name("slowtests.sh"), "noisy.log")


# ---- protocol regressions -----------------------------------------------------------------------

class ProtocolTests(unittest.TestCase):
    def run_control(self, script, env, *args, timeout=30, check=False):
        return subprocess.run(evallib.python_argv(script, *args), cwd=script.parent, env=env,
                              capture_output=True, text=True, timeout=timeout, check=check)

    def run_check(self, root, env, passes):
        check = self.run_control(root / "check.py", env)
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
        cases = [("pmx-cli", "0.02")]
        if not evallib.IS_WINDOWS:
            cases += [("rawtmux", "0.15"), ("shell", "0.02"), ("shell-suite-first", "0.02")]
        for harness, scale in cases:
            with self.subTest(harness=harness), tempfile.TemporaryDirectory(
                    prefix="pmx-m01-test-", dir=None if evallib.IS_WINDOWS else "/tmp") as tmp:
                root = Path(tmp) / "evals/scenarios/M01"
                shutil.copytree(SCRIPT_DIR, root, ignore=shutil.ignore_patterns(
                    "__pycache__", "state", "env.sh", "subgoals.json"))
                for shared in ("evallib.py", "termsupport.py"):
                    shutil.copy2(evallib.EVALS_DIR / shared, root.parents[1] / shared)
                env = os.environ.copy()
                for key in list(env):
                    if key.startswith("PAIRMUX_EVAL_"):
                        del env[key]
                env.update(EVAL_TIME_SCALE=scale, PAIRMUX_EVAL_SOCKET="pmx-m01-" + Path(tmp).name[-6:])
                self.run_control(root / "setup.py", env, check=True)
                try:
                    self.run_check(root, env, set())
                    self.run_control(root / "golden.py", env, "--harness", harness, timeout=90, check=True)
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
                    for event in ("listener_approved", "fatal_reviewed", "suite_batch", "suite_resumed",
                                  "server_stopped", "status_requested"):
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
                    for name in FIXTURES:
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
                    for name in ("check.py", "setup.py", "golden.py"):
                        shutil.copy2(root / name, isolated / name)
                    for shared in ("evallib.py", "termsupport.py"):
                        shutil.copy2(root.parents[1] / shared, isolated.parents[1] / shared)
                    isolated_env = Path(tmp) / "isolated/env.sh"
                    shutil.move(str(root / "env.sh"), isolated_env)
                    for name in ("check.py", "setup.py", "golden.py"):
                        (root / name).unlink()
                    env.update(PAIRMUX_EVAL_SCENARIO_DIR=str(root), PAIRMUX_EVAL_ENV_FILE=str(isolated_env),
                               PAIRMUX_EVAL_SUBGOALS_FILE=str(root / "subgoals.json"))
                    self.run_check(isolated, env, all_ids)
                finally:
                    stop_env = env.copy()
                    stop_env.update(evallib.parse_env_file(env.get("PAIRMUX_EVAL_ENV_FILE")
                                                           or root / "env.sh")[0])
                    evallib.stop_endpoint(env["PAIRMUX_EVAL_SOCKET"], stop_env)
                    if harness in TMUX_HARNESSES:
                        evallib.stop_endpoint(env["PAIRMUX_EVAL_SOCKET"], stop_env, backend="tmux")


# ---- reference solution -------------------------------------------------------------------------

def golden(harness: str) -> None:
    scen = evallib.scenario_dir(__file__)
    evallib.load_env(scen_dir=scen)
    socket = os.environ["PAIRMUX_SOCKET"]
    events_path = scen / "m01-events.jsonl"
    golden_home = None
    if not evallib.IS_WINDOWS:
        # Control-plane only: do not load the host's shell startup files or global CLI
        # settings during infrastructure goldens. No host files/binaries are modified.
        golden_home = Path(tempfile.mkdtemp(prefix="pmx-m01-home-", dir="/tmp"))
        zsh = shutil.which("zsh")
        if zsh:
            os.environ["SHELL"] = zsh
        os.environ.update(HOME=str(golden_home), ZDOTDIR=str(golden_home))
        (golden_home / ".zshenv").write_text(f"export PATH={shlex.quote(os.environ['PATH'])}\n")
    os.chdir(scen)

    def has_event(name):
        try:
            return any(json.loads(line).get("event") == name
                       for line in events_path.read_text().splitlines())
        except (OSError, json.JSONDecodeError):
            return False

    def wait_event(name):
        evallib.wait_until(lambda: has_event(name), 60, "golden: missing logical event " + name)

    def tmux(*args):
        subprocess.run(["tmux", "-L", socket, *args], check=True)

    py = evallib.PYTHON
    try:
        if harness == "pmx-cli":
            evallib.pmx("new", "--name", "m01server", "--cwd", str(scen), "--cmd", f"{py} -I bigserver.py")
            evallib.pmx("new", "--name", "m01tests", "--cwd", str(scen))
            tests = f"{py} slowtests.py" if evallib.IS_WINDOWS else "./slowtests.sh"
            # Returns at its short timeout while the suite keeps running.
            evallib.pmx("run", "m01tests", tests, "--timeout", "1s", check=False)
            evallib.pmx("new", "--name", "m01work", "--cwd", str(scen))
        elif harness == "shell-suite-first":
            # Tests-first startup must be equally valid, even on a very fast machine.
            tmux("new-session", "-d", "-s", "m01", "-n", "tests", "-c", str(scen), "./slowtests.sh")
            wait_event("suite_started")
            tmux("new-window", "-t", "m01", "-n", "server", "-c", str(scen), "python3 -I bigserver.py")
        else:
            tmux("new-session", "-d", "-s", "m01", "-n", "server", "-c", str(scen), "python3 -I bigserver.py")
            tmux("new-window", "-t", "m01", "-n", "tests", "-c", str(scen), "./slowtests.sh")
        wait_event("listener_prompt")
        if harness == "pmx-cli":
            if evallib.IS_WINDOWS:
                # No grep, and PowerShell 5.1 redirection writes UTF-16: write it from Python.
                dig = (f"{py} -c \"import pathlib as p; l=[x for x in p.Path('noisy.log')"
                       ".read_text().splitlines() if 'FATAL' in x]; "
                       "open('answer-fatal.txt','w',newline=chr(10)).write(l[0]+chr(10))\"")
            else:
                dig = "grep -F FATAL noisy.log > answer-fatal.txt"
            evallib.pmx("run", "m01work", dig)
            evallib.pmx("send", "m01server", "--text", "y", "--enter")
        else:
            lines = [line for line in (scen / "noisy.log").read_text().splitlines() if "FATAL" in line]
            with open("answer-fatal.txt", "w", encoding="utf-8", newline="\n") as handle:
                handle.write("".join(line + "\n" for line in lines))
            tmux("send-keys", "-t", "m01:server", "-l", "y")
            tmux("send-keys", "-t", "m01:server", "Enter")
        wait_event("server_ready")
        port = (scen / "server-port.txt").read_text().strip()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=10) as response:
            (scen / "answer-server.txt").write_bytes(response.read())
        wait_event("suite_completed")
        shutil.copyfile(scen / "test-report.txt", scen / "answer-tests.txt")
        if harness == "pmx-cli":
            evallib.pmx("send", "m01server", "--key", "C-c")
        else:
            tmux("send-keys", "-t", "m01:server", "C-c")
        wait_event("server_stopped")
        with open(scen / "DONE.txt", "w", encoding="utf-8", newline="\n") as handle:
            handle.write("all three complete\n")
    finally:
        evallib.stop_endpoint(socket)
        if harness in TMUX_HARNESSES:
            evallib.stop_endpoint(socket, backend="tmux")
        if golden_home is not None:
            shutil.rmtree(golden_home, ignore_errors=True)


def main(argv: list[str]) -> int:
    if argv[:1] == ["--self-test"]:
        unittest.main(argv=["m01-protocol"], verbosity=2)
        return 0
    harness = "pmx-cli"
    if argv[:1] == ["--harness"] and len(argv) == 2:
        harness = argv[1]
    elif argv:
        return 2
    if harness not in HARNESSES:
        return 2
    if harness in TMUX_HARNESSES and evallib.IS_WINDOWS:
        print(f"golden: the {harness} harness drives host tmux; tmux harnesses are unavailable on "
              "Windows (use --harness pmx-cli)", file=sys.stderr)
        return 2
    golden(harness)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
