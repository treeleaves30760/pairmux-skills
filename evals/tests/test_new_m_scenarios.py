#!/usr/bin/env python3
"""Zero-cost M02/M04/M05/M06/M08 fixture tests; only owned tmux endpoints."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import unittest
import uuid

EVALS = Path(__file__).resolve().parents[1]
SCENARIOS = ("M02", "M04", "M05", "M06", "M08")
PRIVATE = {"TASK.md", "setup.sh", "check.sh", "env.sh", "golden.sh", "human.sh"}
TEST_SHELL = shutil.which('zsh') or shutil.which('bash')
REAL_BIN = os.environ.get('PAIRMUX_REAL_BIN', '')
LIVE_TOOLS = (os.name == 'posix' and TEST_SHELL and shutil.which('tmux') and shutil.which('curl')
              and bool(REAL_BIN) and os.access(REAL_BIN, os.X_OK))


class Fixture:
    def __init__(self, scenario):
        self.tmp = tempfile.TemporaryDirectory(prefix="pmx-new-m-", dir="/tmp")
        try:
            self.initialize(scenario)
        except BaseException:
            self.tmp.cleanup()
            raise

    def initialize(self, scenario):
        root = Path(self.tmp.name)
        self.work = root / "work" / scenario
        self.control = root / "control"
        self.scripts = self.control / "evals" / "scenarios" / scenario
        self.state = self.control / "runtime" / "state"
        self.work.mkdir(parents=True)
        self.scripts.mkdir(parents=True)
        shutil.copy2(EVALS / "lib.sh", self.control / "evals" / "lib.sh")
        for path in (EVALS / "scenarios" / scenario).iterdir():
            if not path.is_file():
                continue
            destination = self.scripts if path.name in PRIVATE else self.work
            shutil.copy2(path, destination / path.name)
        self.socket = "pmx-new-m-" + uuid.uuid4().hex[:12]
        binary = REAL_BIN
        home = root / 'home'
        home.mkdir()
        self.env = dict(os.environ, HOME=str(home), SHELL=TEST_SHELL,
                        PAIRMUX_REAL_BIN=binary, PAIRMUX_BIN=binary,
                        PAIRMUX_EVAL_SOCKET=self.socket,
                        PAIRMUX_EVAL_SCENARIO_DIR=str(self.work),
                        PAIRMUX_EVAL_STATE_DIR=str(self.state),
                        PAIRMUX_EVAL_CONTROL_ROOT=str(self.control),
                        PAIRMUX_EVAL_ENV_FILE=str(self.control / "runtime" / "env.sh"),
                        PAIRMUX_EVAL_SUBGOALS_FILE=str(root / "subgoals.json"),
                        EVAL_TIME_SCALE="0.15")

    def run(self, name, *, success=True, timeout=75, args=()):
        process = subprocess.Popen([str(self.scripts / name), *args], cwd=self.work,
                                   env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
            raise AssertionError(f"{name} timed out\n{output.decode(errors='replace')}")
        text = output.decode(errors="replace")
        if success and process.returncode:
            raise AssertionError(f"{name} exited {process.returncode}\n{text}")
        return process.returncode, text

    def ledger(self):
        return json.loads(Path(self.env["PAIRMUX_EVAL_SUBGOALS_FILE"]).read_text())["subgoals"]

    def close(self):
        # The only server we ever kill is this fixture's randomly named endpoint.
        subprocess.run(["tmux", "-L", self.socket, "kill-server"], env=self.env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        pid_file = self.state / "m06-human" / "human.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGTERM)
            except (ValueError, ProcessLookupError):
                pass
        self.tmp.cleanup()


@unittest.skipUnless(LIVE_TOOLS, 'set PAIRMUX_REAL_BIN to a trusted real CLI; tmux, curl and zsh/bash are required')
class NewMScenarios(unittest.TestCase):
    def fixture(self, scenario):
        fixture = Fixture(scenario)
        self.addCleanup(fixture.close)
        fixture.run("setup.sh")
        self.assertFalse(any((fixture.work / name).exists() for name in PRIVATE))
        return fixture

    def golden(self, scenario):
        fixture = self.fixture(scenario)
        fixture.run("golden.sh")
        fixture.run("check.sh")
        entries = fixture.ledger()
        self.assertEqual(len(entries), 5)
        self.assertTrue(all(entry["pass"] for entry in entries))
        self.assertTrue(all(entry["detail"].startswith(("capability:", "admin:", "safety:"))
                            for entry in entries))
        return fixture

    def reject(self, fixture, *ids):
        code, output = fixture.run("check.sh", success=False)
        self.assertNotEqual(code, 0, output)
        failed = {entry["id"] for entry in fixture.ledger() if not entry["pass"]}
        self.assertTrue(set(ids) <= failed, (ids, failed, output))

    def mutate_events(self, fixture, filename, update):
        path = fixture.work / filename
        original = path.read_bytes()
        records = [json.loads(line) for line in original.splitlines()]
        update(records)
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
        return lambda: path.write_bytes(original)

    def test_untouched_and_handwritten_outputs_fail(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                fixture = self.fixture(scenario)
                self.reject(fixture)
                for name in ("deployment.txt", "a-first.txt", "a-second.txt", "a-third.txt",
                             "b-first.txt", "b-second.txt", "alpha.txt", "beta.txt",
                             "recovery.txt", "release.txt", "tests.txt", "docs.txt",
                             "answer-server.txt", "answer-request.txt"):
                    (fixture.work / name).write_text("pretend completed\n")
                self.reject(fixture)

    def test_exec_pipes_do_not_fabricate_live_capabilities(self):
        commands = {'M02': ('flow.py', 'repl'), 'M04': ('identity.py', 'A1'),
                    'M05': ('job.py', 'hang'), 'M06': ('queue.py', 'checkpoint'),
                    'M08': ('server.py',)}
        for scenario, command in commands.items():
            with self.subTest(scenario=scenario):
                fixture = self.fixture(scenario)
                process = subprocess.run(['python3', '-I', *command], cwd=fixture.work,
                                         env=fixture.env, input=b'1234 * 5678\nY\nq\n',
                                         capture_output=True, timeout=10)
                self.assertNotEqual(process.returncode, 0)
                self.reject(fixture)

    def test_m02_golden_and_confirmation_pager_evidence(self):
        fixture = self.fixture("M02")
        # The live REPL may display by print() or its normal displayhook.
        golden = fixture.scripts / 'golden.sh'
        golden.write_text(golden.read_text().replace("--text '1234 * 5678'", "--text 'print(1234 * 5678)'"))
        fixture.run('golden.sh')
        fixture.run('check.sh')
        restore = self.mutate_events(fixture, "interaction.jsonl",
                                    lambda rows: rows.append(next(dict(row) for row in rows
                                                                  if row["event"] == "confirmation")))
        self.reject(fixture, "one_confirmation", "deployment_complete")
        restore()
        restore = self.mutate_events(fixture, "interaction.jsonl",
                                    lambda rows: rows.__setitem__(slice(None), [row for row in rows
                                                                             if row["event"] != "pager_exit"]))
        self.reject(fixture, "pager_exited", "deployment_complete")
        restore()
        restore = self.mutate_events(fixture, "interaction.jsonl",
                                    lambda rows: [row.update(source='7006652') for row in rows if row['event'] == 'repl_input'])
        self.reject(fixture, "repl_live_result", "value_propagated")
        restore()
        restore = self.mutate_events(fixture, "interaction.jsonl",
                                    lambda rows: [row.update(source='unused=1234*5678; print(7006652)') for row in rows if row['event'] == 'repl_input'])
        self.reject(fixture, "repl_live_result", "value_propagated")
        restore()
        self.mutate_events(fixture, "interaction.jsonl",
                           lambda rows: [row.update(tty=None) for row in rows])
        self.reject(fixture, "repl_live_result", "value_propagated")

    def test_m02_live_variable_product_is_accepted(self):
        for expression in ('left=1234; right=5678; left*right',
                           'left=1234; right=5678; product=left*right; print(product)',
                           'left=1234\nright=5678\nproduct=left*right\nprint(product)'):
            with self.subTest(expression=expression):
                fixture = self.fixture('M02')
                golden = fixture.scripts / 'golden.sh'
                golden.write_text(golden.read_text().replace("--text '1234 * 5678'", f"--text '{expression}'"))
                fixture.run('golden.sh')
                fixture.run('check.sh')
                self.assertTrue(all(entry['pass'] for entry in fixture.ledger()))

    def test_m02_live_canned_result_is_rejected(self):
        for expression in ('7006652', 'unused=1234*5678; print(7006652)'):
            with self.subTest(expression=expression):
                fixture = self.fixture('M02')
                golden = fixture.scripts / 'golden.sh'
                golden.write_text(golden.read_text().replace("--text '1234 * 5678'", f"--text '{expression}'"))
                fixture.run('golden.sh')
                self.reject(fixture, 'repl_live_result', 'value_propagated', 'deployment_complete')

    def test_m04_repeated_setup_is_rejected(self):
        for setup in ('source ../venv/bin/activate; export TOKEN=fixture-only-m04; ',
                      'source ../venv/bin/activate; ', 'export TOKEN=fixture-only-m04; '):
            with self.subTest(setup=setup):
                fixture = self.fixture('M04')
                golden = fixture.scripts / 'golden.sh'
                source = golden.read_text()
                for step in ('A2', 'A3'):
                    source = source.replace(f"'python ../identity.py {step}'", f"'{setup}python ../identity.py {step}'")
                golden.write_text(source)
                fixture.run('golden.sh')
                self.reject(fixture, 'state_persisted', 'commands_completed')

    def test_m04_observer_portable_exports_and_once_only(self):
        shells = [path for path in (shutil.which('bash'), shutil.which('zsh')) if path]
        for shell in shells:
            with self.subTest(shell=shell):
                fixture = self.fixture('M04')
                fixture.env['SHELL'] = shell
                golden = fixture.scripts / 'golden.sh'
                source = golden.read_text().replace("pmx run m04a 'python ../identity.py A2'",
                    "pmx run m04a 'export UNRELATED=still-ok; export PATH=\"$PATH\"; export UNRELATED; "
                    "test \"$UNRELATED\" = still-ok && python ../identity.py A2'")
                golden.write_text(source)
                activation = fixture.work / 'venv' / 'bin' / 'activate'
                subprocess.run([shell, '-n', str(activation)], check=True, capture_output=True)
                if shutil.which('shellcheck'):
                    # Python's stdlib activation has known generated quoting;
                    # lint everything else, including our appended source stanza.
                    subprocess.run(['shellcheck', '-s', 'bash', '-x', '-e', 'SC2140', str(activation)],
                                   check=True, capture_output=True)
                fixture.run('golden.sh')
                fixture.run('check.sh')
                self.assertEqual([row['event'] for row in map(json.loads,
                    (fixture.work / 'environment.jsonl').read_text().splitlines())], ['activation', 'token_export'])
            for repeated in ('source ../venv/bin/activate; ', 'export TOKEN=fixture-only-m04; '):
                with self.subTest(shell=shell, repeated=repeated):
                    fixture = self.fixture('M04')
                    fixture.env['SHELL'] = shell
                    golden = fixture.scripts / 'golden.sh'
                    source = golden.read_text().replace("'python ../identity.py A2'", f"'{repeated}python ../identity.py A2'")
                    golden.write_text(source)
                    fixture.run('golden.sh')
                    self.reject(fixture, 'state_persisted', 'commands_completed')

    def test_m04_golden_and_real_identity(self):
        fixture = self.golden("M04")
        restore = self.mutate_events(fixture, "identity.jsonl",
                                    lambda rows: next(row for row in rows if row["step"] == "A2").update(prefix="/fake"))
        self.reject(fixture, "venv_interpreter", "state_persisted")
        restore()
        restore = self.mutate_events(fixture, "identity.jsonl",
                                    lambda rows: next(row for row in rows if row["step"] == "A3").update(ppid=1))
        self.reject(fixture, "state_persisted")
        restore()
        restore = self.mutate_events(fixture, 'environment.jsonl',
                                    lambda rows: rows.append(dict(rows[0], activation_count=2)))
        self.reject(fixture, 'state_persisted', 'commands_completed')
        restore()
        self.mutate_events(fixture, "identity.jsonl",
                           lambda rows: next(row for row in rows if row["step"] == "B1").update(token="fixture-only-m04"))
        self.reject(fixture, "b_isolated")
        (fixture.work / 'observe-env.sh').write_text('# bypassed observer\n')
        self.reject(fixture, 'venv_interpreter', 'state_persisted', 'commands_completed')

    def test_m05_golden_and_in_place_sigint(self):
        fixture = self.golden("M05")
        restore = self.mutate_events(fixture, "jobs.jsonl",
                                    lambda rows: next(row for row in rows if row["event"] == "interrupted").update(signal="SIGTERM"))
        self.reject(fixture, "sigint_trapped", "same_terminal_reused")
        restore()
        restore = self.mutate_events(fixture, "jobs.jsonl",
                                    lambda rows: next(row for row in rows if row["event"] == "recovered").update(sid=1))
        self.reject(fixture, "same_terminal_reused")
        restore()
        restore = self.mutate_events(fixture, "jobs.jsonl",
                                    lambda rows: next(row for row in rows if row["event"] == "progress").update(time_ns=1))
        self.reject(fixture, "three_jobs_overlap", "other_jobs_unaffected")
        restore()
        self.mutate_events(fixture, "jobs.jsonl",
                           lambda rows: rows.append(dict(next(row for row in rows if row["job"] == "alpha"),
                                                        event="interrupted", signal="SIGINT")))
        self.reject(fixture, "other_jobs_unaffected")

    def test_m06_golden_and_private_revision_order_ack(self):
        fixture = self.golden("M06")
        proof = fixture.state / "m06-human" / "revision.json"
        original = proof.read_bytes()
        proof.unlink()
        self.reject(fixture, "human_revision", "revision_acknowledged", "priority_order")
        proof.write_bytes(original)
        restore = self.mutate_events(fixture, "queue.jsonl",
                                    lambda rows: next(row for row in rows if row["event"] == "acknowledged").update(revision="invented"))
        self.reject(fixture, "revision_acknowledged", "priority_order")
        restore()
        self.mutate_events(fixture, "queue.jsonl",
                           lambda rows: [row.update(job={'release': 'docs', 'docs': 'release'}.get(row['job'], row['job']))
                                         for row in rows if row['event'] in ('started', 'completed')])
        self.reject(fixture, "priority_order")

    def test_m08_golden_and_exact_request_readback(self):
        fixture = self.golden("M08")
        (fixture.work / "answer-request.txt").write_text("REQUEST invented\n")
        self.reject(fixture, "request_readback")
        restore = self.mutate_events(fixture, "server-events.jsonl",
                                    lambda rows: next(row for row in rows if row["event"] == "request").update(user_agent="not-curl"))
        self.reject(fixture, "curl_verified")
        restore()
        restore = self.mutate_events(fixture, "server-events.jsonl",
                                    lambda rows: rows.append(dict(next(row for row in rows if row["event"] == "request"))))
        self.reject(fixture, "single_request")
        restore()
        self.mutate_events(fixture, "server-events.jsonl",
                           lambda rows: rows.__setitem__(slice(None), [row for row in rows if row["event"] != "stopped"]))
        self.reject(fixture, "clean_shutdown")


if __name__ == "__main__":
    unittest.main()
