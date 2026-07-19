#!/usr/bin/env python3
"""Tests for the model-free eval runner harness."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import unittest


EVALS_DIR = Path(__file__).resolve().parents[1]
RUNNER = EVALS_DIR / "run.py"
MOCK_BIN = Path(__file__).with_name("mock_bin.py")
SPEC = importlib.util.spec_from_file_location("pairmux_eval_run", RUNNER)
assert SPEC and SPEC.loader
eval_run = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = eval_run
SPEC.loader.exec_module(eval_run)


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pairmux-eval-test-")
        self.root = Path(self.temporary.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        for name in ("opencode", "claude", "codex", "pairmux"):
            target = self.bin_dir / name
            shutil.copy2(MOCK_BIN, target)
            target.chmod(0o755)
        self.agent_log = self.root / "agent.jsonl"
        self.env = os.environ.copy()
        self.env.update(
            {
                "PATH": str(self.bin_dir) + os.pathsep + self.env.get("PATH", ""),
                "PAIRMUX_MOCK_AGENT_LOG": str(self.agent_log),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        runner_arguments = list(arguments)
        if "--pairmux-bin" not in runner_arguments:
            runner_arguments.extend(["--pairmux-bin", str(self.bin_dir / "pairmux")])
        return subprocess.run(
            [sys.executable, str(RUNNER), *runner_arguments],
            cwd=EVALS_DIR.parent,
            env=env or self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )

    def result_for(self, completed: subprocess.CompletedProcess[str]) -> tuple[Path, dict[str, object]]:
        run_root = Path(completed.stdout.strip().splitlines()[-1])
        with (run_root / "results.jsonl").open(encoding="utf-8") as stream:
            result = json.loads(stream.readline())
        return run_root, result

    def test_scenario_selectors_support_repeats_and_ranges(self) -> None:
        available = {1: "S01", 2: "S02", 3: "S03", 6: "S06"}
        self.assertEqual(eval_run.parse_scenarios(["S01-S03", "6", "S02"], available), ["S01", "S02", "S03", "S06"])
        with self.assertRaisesRegex(ValueError, "ascending"):
            eval_run.parse_scenarios(["S03-S01"], available)
        with self.assertRaisesRegex(ValueError, "unknown"):
            eval_run.parse_scenarios(["S04"], available)

    def test_proxy_preserves_literal_argv_and_nonzero_exit(self) -> None:
        runtime = Path(tempfile.mkdtemp(prefix="pmx-proxy-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, runtime, True)
        proxy = runtime / "bin" / "pairmux"
        proxy.parent.mkdir(parents=True)
        shutil.copy2(EVALS_DIR / "pairmux_proxy.py", proxy)
        proxy.chmod(0o755)
        real = runtime / "real-pairmux"
        shutil.copy2(self.bin_dir / "pairmux", real)
        real.chmod(0o755)
        broker_env = self.env.copy()
        broker_env.pop("PAIRMUX_STATE_NAMESPACE", None)
        broker_env.update(
            {
                "PAIRMUX_SOCKET": "proxy-test",
                "PAIRMUX_STATE_DIR": str(self.root / "proxy-state"),
            }
        )
        broker = eval_run.PairmuxBroker(
            runtime / "broker.sock",
            real_pairmux=real,
            real_pairmux_sha256=eval_run.sha256_file(real),
            fixed_env=broker_env,
            allowed_cwd=self.root,
            expected_socket="proxy-test",
        )
        broker.start()
        client_env = broker_env.copy()
        client_env.update(
            {
                "PAIRMUX_SOCKET": "client-forged-socket",
                "PAIRMUX_STATE_DIR": str(self.root / "client-forged-state"),
                "PAIRMUX_REAL_BIN": "/client/cannot/choose/this",
            }
        )
        argv = ["mock-fail", "two words", "$(literal)", "quote'and\"double"]
        try:
            completed = subprocess.run(
                [str(proxy), *argv],
                cwd=self.root,
                env=client_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        finally:
            trace = broker.stop_and_finalize()
        self.assertEqual(completed.returncode, 23, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "broker stdout preserved")
        self.assertEqual(completed.stderr.strip(), "broker stderr preserved")
        self.assertEqual(trace.errors, [])
        self.assertEqual(trace.rejections, [])
        self.assertEqual(len(trace.calls), 1)
        record = trace.calls[0]
        self.assertEqual(record["argv"], argv)
        self.assertEqual(record["exit_code"], 23)
        self.assertIsInstance(record["pid"], int)
        self.assertEqual(record["process_group"], record["pid"])
        self.assertEqual(record["client_uid"], os.geteuid())
        self.assertEqual(record["pairmux_socket"], "proxy-test")
        self.assertEqual(record["pairmux_state_dir"], str(self.root / "proxy-state"))
        self.assertTrue(record["started_at"])
        self.assertTrue(record["finished_at"])

    def test_shell_path_guard_survives_login_shell_path_rewrites(self) -> None:
        runtime = self.root / "guard-runtime"
        guard = eval_run.install_shell_path_guard(runtime, self.bin_dir)
        self.addCleanup(shutil.rmtree, Path(guard["BASH_ENV"]).parent, True)
        env = os.environ.copy()
        env.update(guard)
        completed = subprocess.run(
            ["bash", "-c", "command -v pairmux"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(Path(completed.stdout.strip()).resolve(), (self.bin_dir / "pairmux").resolve())
        zsh = shutil.which("zsh")
        if zsh:
            completed = subprocess.run(
                [zsh, "-lc", "command -v pairmux"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                Path(completed.stdout.strip()).resolve(),
                (self.bin_dir / "pairmux").resolve(),
            )

    def test_dry_run_has_no_side_effects_and_passes_task_as_argv(self) -> None:
        output_dir = self.root / "dry-output"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01-S02",
            "--repeat",
            "2",
            "--output-dir",
            str(output_dir),
            "--dry-run",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        plans = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(len(plans), 4)
        self.assertFalse(output_dir.exists())
        self.assertFalse(self.agent_log.exists())
        task = (EVALS_DIR / "scenarios" / "S01" / "TASK.md").read_text(encoding="utf-8")
        first_argv = plans[0]["argv"]
        self.assertIn(task, first_argv)
        self.assertFalse(any("$(cat" in value for value in first_argv))

    def test_generated_env_shell_quotes_output_paths(self) -> None:
        output_dir = self.root / "runs-$(touch INJECTED)"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(output_dir),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_root, result = self.result_for(completed)
        scenario_dir = run_root / result["paths"]["episode"] / "work/S01"
        self.assertFalse((scenario_dir / "INJECTED").exists())
        self.assertFalse((self.root / "INJECTED").exists())
        self.assertFalse((scenario_dir / "env.sh").exists())
        env_artifact = run_root / result["paths"]["episode"] / "runner-artifacts/env.sh"
        self.assertNotIn("$(touch INJECTED)", env_artifact.read_text(encoding="utf-8"))

    def test_generated_env_shell_quotes_tmpdir(self) -> None:
        tmpdir = self.root / "tmp-$(touch INJECTED_TMPDIR)"
        tmpdir.mkdir()
        env = self.env.copy()
        env["TMPDIR"] = str(tmpdir)
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "tmpdir-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse((self.root / "INJECTED_TMPDIR").exists())

    def test_setup_refuses_to_delete_unexpected_state_directory(self) -> None:
        scenario_dir = eval_run.copy_scenario("S01", self.root / "state-guard-work")
        outside = self.root / "must-survive"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_text("keep", encoding="utf-8")
        env = self.env.copy()
        env.update(
            {
                "PAIRMUX_EVAL_STATE_DIR": str(outside),
                "PAIRMUX_REAL_BIN": str(self.bin_dir / "pairmux"),
            }
        )
        completed = subprocess.run(
            [str(scenario_dir / "setup.sh")],
            cwd=scenario_dir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(sentinel.is_file())
        self.assertIn("refusing to reset unexpected eval state directory", completed.stderr)

    def test_all_agent_adapters_run_without_a_model(self) -> None:
        for agent in ("opencode", "claude", "codex"):
            with self.subTest(agent=agent):
                self.agent_log.unlink(missing_ok=True)
                output_dir = self.root / f"runs-{agent}"
                completed = self.invoke(
                    "--agent",
                    agent,
                    "--scenario",
                    "S01",
                    "--timeout",
                    "5",
                    "--output-dir",
                    str(output_dir),
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                run_root, result = self.result_for(completed)
                self.assertTrue(result["pass"])
                self.assertEqual(result["steps"], 2)
                self.assertEqual(result["failure_class"], None)
                self.assertEqual(result["broker_policy_rejections"], 0)
                self.assertEqual(result["agent_version"], f"{agent} mock-1.0")
                self.assertEqual(result["model"], "default")
                self.assertEqual(result["pairmux_path"], str((self.bin_dir / "pairmux").resolve()))
                self.assertEqual(result["pairmux_sha256"], eval_run.sha256_file(self.bin_dir / "pairmux"))
                self.assertTrue((run_root / "summary.json").is_file())
                self.assertTrue((run_root / "summary.md").is_file())
                skill_dir = run_root / result["skill_install_dir"]
                self.assertTrue((skill_dir / "SKILL.md").is_file())
                self.assertEqual(result["skill_tree_sha256"], eval_run.sha256_tree(skill_dir))
                self.assertEqual(result["skill_tree_sha256"], eval_run.sha256_tree(eval_run.SKILL_SOURCE))

                invocation = json.loads(self.agent_log.read_text(encoding="utf-8").splitlines()[0])
                task = (EVALS_DIR / "scenarios" / "S01" / "TASK.md").read_text(encoding="utf-8")
                self.assertEqual(invocation["task_arguments"], [task])
                self.assertTrue(invocation["loaded_skill_exists"])
                self.assertEqual(Path(invocation["loaded_skill"]).resolve(), Path(result["skill_discovery_path"]).resolve() / "SKILL.md")
                self.assertIsNone(invocation["host_poison"])
                self.assertIsNone(invocation["real_bin_exposed"])
                argv = invocation["argv"]
                if agent == "opencode":
                    self.assertIn("--pure", argv)
                    self.assertIn("--auto", argv)
                    self.assertIn("--print-logs", argv)
                    self.assertEqual(argv[argv.index("--log-level") + 1], "ERROR")
                    self.assertEqual(argv[argv.index("--format") + 1], "json")
                    scenario_dir = run_root / result["paths"]["episode"] / "work/S01"
                    self.assertEqual(
                        Path(argv[argv.index("--dir") + 1]).resolve(), scenario_dir.resolve()
                    )
                    self.assertEqual(invocation["opencode_disable_project_config"], "1")
                    self.assertTrue((scenario_dir / ".git").is_dir())
                    self.assertEqual(
                        Path(result["agent_project_isolation"]["path"]).resolve(),
                        scenario_dir.resolve(),
                    )
                    self.assertEqual(
                        result["agent_project_isolation"]["method"],
                        "nested-committed-git-root",
                    )
                    self.assertRegex(
                        str(result["agent_project_isolation"]["commit"]),
                        r"^[0-9a-f]{40}$",
                    )
                    git_head = subprocess.run(
                        ["git", "-C", str(scenario_dir), "rev-parse", "HEAD"],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=5,
                    ).stdout.strip()
                    self.assertEqual(
                        result["agent_project_isolation"]["commit"], git_head
                    )
                    git_status = subprocess.run(
                        ["git", "-C", str(scenario_dir), "status", "--porcelain"],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=5,
                    ).stdout
                    self.assertEqual(git_status, "")
                elif agent == "claude":
                    self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
                else:
                    self.assertEqual(argv[argv.index("--sandbox") + 1], "danger-full-access")
                    self.assertIn("--json", argv)
                    self.assertTrue(invocation["codex_home_exists"])

                calls_path = run_root / result["paths"]["pairmux_calls"]
                calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
                rejections_path = run_root / result["paths"]["broker_rejections"]
                self.assertEqual(rejections_path.read_text(encoding="utf-8"), "")
                self.assertEqual(calls[0]["argv"], ["new", "--name", "mock"])
                self.assertEqual(
                    calls[1]["argv"],
                    ["run", "mock", "printf '%s\\n' PAIRMUX-S01-OK"],
                )
                self.assertEqual([call["exit_code"] for call in calls], [0, 0])
                self.assertTrue(all(call["started_at"] for call in calls))
                self.assertTrue(all(call["finished_at"] for call in calls))

    def test_repeats_use_distinct_episode_socket_and_state(self) -> None:
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--repeat",
            "2",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "repeat-runs"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_root = Path(completed.stdout.strip().splitlines()[-1])
        results = [
            json.loads(line)
            for line in (run_root / "results.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(results), 2)
        self.assertEqual({result["repeat"] for result in results}, {1, 2})
        self.assertEqual(len({result["episode_id"] for result in results}), 2)
        self.assertEqual(len({result["socket"] for result in results}), 2)
        self.assertEqual(len({result["state_dir"] for result in results}), 2)

    def test_timeout_kills_agent_process_group_and_still_checks(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "hang"
        env["PAIRMUX_MOCK_CHILD_LOG"] = str(self.root / "child.jsonl")
        completed = self.invoke(
            "--agent",
            "claude",
            "--scenario",
            "S01",
            "--timeout",
            "0.5",
            "--output-dir",
            str(self.root / "timeout-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        run_root, result = self.result_for(completed)
        self.assertEqual(result["failure_class"], "agent_timeout")
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["pass"])
        self.assertTrue((run_root / result["paths"]["check_stdout"]).is_file())
        self.assertTrue((run_root / result["paths"]["check_stderr"]).is_file())

    def test_provider_rate_limit_fails_fast_and_stops_remaining_episodes(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "provider_rate_limited"
        env["PAIRMUX_MOCK_CHILD_LOG"] = str(self.root / "provider-child.jsonl")
        completed = self.invoke(
            "--agent",
            "opencode",
            "--provider",
            "opencode",
            "--model",
            "opencode/big-pickle",
            "--acceptance-profile",
            "p4",
            "--scenario",
            "S01-S02",
            "--repeat",
            "2",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "provider-rate-limit-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 1)
        run_root, result = self.result_for(completed)
        self.assertEqual(result["failure_class"], "provider_rate_limited")
        self.assertEqual(result["agent_observed_failure_class"], "provider_rate_limited")
        self.assertFalse(result["timed_out"])
        self.assertLess(float(result["wall_time_seconds"]), 4.0)
        self.assertIn("STOP schedule", completed.stderr)
        self.assertEqual(len((run_root / "results.jsonl").read_text().splitlines()), 1)

        summary_text = (run_root / "summary.json").read_text(encoding="utf-8")
        summary = json.loads(summary_text)
        self.assertEqual(summary["stop_reason"], "provider_rate_limited")
        self.assertEqual(
            summary["schedule"],
            {
                "planned_episodes": 4,
                "completed_episodes": 1,
                "skipped_episodes": 3,
                "stopped_early": True,
                "stop_reason": "provider_rate_limited",
            },
        )
        self.assertFalse(summary["acceptance"]["eligible"])
        self.assertNotIn("Rate limit exceeded", summary_text)
        self.assertIn(
            "AI_APICallError: Rate limit exceeded",
            (run_root / result["paths"]["episode"] / "agent.stderr.log").read_text(
                encoding="utf-8"
            ),
        )

        child = json.loads(
            (self.root / "provider-child.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        with self.assertRaises(ProcessLookupError):
            os.kill(int(child["pid"]), 0)

    def test_provider_rate_limit_is_classified_when_agent_exits_immediately(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "provider_rate_limited_exit"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "provider-rate-limit-exit-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 1)
        run_root, result = self.result_for(completed)
        self.assertEqual(result["failure_class"], "provider_rate_limited")
        self.assertFalse(result["timed_out"])
        summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
        self.assertFalse(summary["schedule"]["stopped_early"])
        self.assertEqual(summary["schedule"]["skipped_episodes"], 0)
        self.assertEqual(summary["stop_reason"], "provider_rate_limited")

    def test_other_provider_failures_are_classified_and_stop_schedule(self) -> None:
        for mode in ("provider_auth_failed", "provider_unavailable"):
            with self.subTest(mode=mode):
                env = self.env.copy()
                env["PAIRMUX_MOCK_MODE"] = mode
                completed = self.invoke(
                    "--agent",
                    "opencode",
                    "--scenario",
                    "S01-S02",
                    "--timeout",
                    "5",
                    "--output-dir",
                    str(self.root / f"{mode}-runs"),
                    env=env,
                )
                self.assertEqual(completed.returncode, 1)
                run_root, result = self.result_for(completed)
                self.assertEqual(result["failure_class"], mode)
                self.assertFalse(result["timed_out"])
                summary = json.loads(
                    (run_root / "summary.json").read_text(encoding="utf-8")
                )
                self.assertEqual(summary["stop_reason"], mode)
                self.assertEqual(summary["schedule"]["completed_episodes"], 1)
                self.assertEqual(summary["schedule"]["skipped_episodes"], 1)

    def test_opencode_silent_hang_remains_agent_timeout(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "hang"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "0.5",
            "--output-dir",
            str(self.root / "opencode-timeout-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 1)
        _run_root, result = self.result_for(completed)
        self.assertEqual(result["failure_class"], "agent_timeout")
        self.assertTrue(result["timed_out"])
        self.assertIsNone(result["agent_observed_failure_class"])

    def test_provider_error_text_on_stdout_does_not_trigger_detector(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "provider_error_text_stdout"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "provider-error-stdout-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        _run_root, result = self.result_for(completed)
        self.assertTrue(result["pass"])
        self.assertIsNone(result["agent_observed_failure_class"])

    def test_provider_rate_limit_cannot_be_misclassified_as_handoff(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "provider_rate_limited"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S05",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "provider-rate-limit-handoff-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 1)
        _run_root, result = self.result_for(completed)
        self.assertFalse(result["pass"])
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["failure_class"], "provider_rate_limited")

    def test_timeout_preserves_interrupted_proxy_call_record(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "hang_pairmux"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "0.5",
            "--output-dir",
            str(self.root / "proxy-timeout-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        run_root, result = self.result_for(completed)
        self.assertEqual(result["failure_class"], "agent_timeout")
        self.assertEqual(result["steps"], 1)
        calls_path = run_root / result["paths"]["pairmux_calls"]
        call = json.loads(calls_path.read_text(encoding="utf-8"))
        self.assertEqual(call["argv"], ["run", "mock", "HANG-FOREVER"])
        self.assertIsInstance(call["exit_code"], int)
        self.assertLess(call["exit_code"], 0)
        self.assertTrue(call["finished_at"])

    def test_s05_human_handoff_timeout_is_an_expected_pass(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "human_handoff"
        completed = self.invoke(
            "--agent",
            "claude",
            "--scenario",
            "S05",
            "--timeout",
            "1.5",
            "--output-dir",
            str(self.root / "handoff-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_root, result = self.result_for(completed)
        self.assertTrue(result["pass"])
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["outcome"], "expected_human_handoff")
        self.assertIsNone(result["failure_class"])
        calls_path = run_root / result["paths"]["pairmux_calls"]
        calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(eval_run.calls_have_human_wait(calls, require_interrupted=True))
        self.assertIn("PASS", (run_root / result["paths"]["check_stdout"]).read_text(encoding="utf-8"))

    def test_s05_completed_short_human_wait_cannot_pass_via_transcript(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "completed_handoff"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S05",
            "--timeout",
            "2",
            "--output-dir",
            str(self.root / "completed-handoff-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        run_root, result = self.result_for(completed)
        self.assertFalse(result["pass"])
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["failure_class"], "check_failed")
        calls_path = run_root / result["paths"]["pairmux_calls"]
        calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
        self.assertFalse(eval_run.calls_have_human_wait(calls, require_interrupted=True))
        self.assertIn(
            "lacked runner deadline/PID proof",
            (run_root / result["paths"]["check_stderr"]).read_text(encoding="utf-8"),
        )

    def test_human_wait_proof_requires_effective_interrupted_subcommand(self) -> None:
        false_positives = [
            {"argv": ["run", "t1", "echo wait", "--human"], "exit_code": -15},
            {"argv": ["--socket", "wait", "ls", "--human"], "exit_code": -15},
            {"argv": ["wait", "t1", "--human", "--timeout", "1ms"], "exit_code": 0},
        ]
        self.assertFalse(
            eval_run.calls_have_human_wait(false_positives, require_interrupted=True)
        )
        proof = {
            "argv": ["--json", "--socket=eval", "wait", "t1", "--human", "--notify"],
            "exit_code": -15,
            "runner_timeout_interrupted": True,
            "runner_timeout_pid_live": True,
            "runner_timeout_client_live": True,
            "runner_timeout_client_ancestry_match": True,
        }
        self.assertTrue(eval_run.calls_have_human_wait([proof], require_interrupted=True))

    def test_s05_proof_rejects_early_signal_wrong_terminal_missing_notify_and_timeout(self) -> None:
        run_secret = {"argv": ["run", "secret", "./secret.sh"], "exit_code": 0}
        counterexamples = [
            {
                "argv": ["wait", "secret", "--human", "--notify"],
                "received_signals": [15],
                "exit_code": -15,
            },
            {
                "argv": ["wait", "other", "--human", "--notify"],
                "runner_timeout_interrupted": True,
                "runner_timeout_pid_live": True,
                "runner_timeout_client_live": True,
                "runner_timeout_client_ancestry_match": True,
            },
            {
                "argv": ["wait", "secret", "--human"],
                "runner_timeout_interrupted": True,
                "runner_timeout_pid_live": True,
                "runner_timeout_client_live": True,
                "runner_timeout_client_ancestry_match": True,
            },
            {
                "argv": ["wait", "secret", "--human", "--notify", "--timeout", "30s"],
                "runner_timeout_interrupted": True,
                "runner_timeout_pid_live": True,
                "runner_timeout_client_live": True,
                "runner_timeout_client_ancestry_match": True,
            },
        ]
        for call in counterexamples:
            with self.subTest(call=call):
                self.assertIsNone(eval_run.s05_handoff_call([run_secret, call]))
        interrupted_wait = {
            "argv": ["wait", "secret", "--human", "--notify"],
            "runner_timeout_interrupted": True,
            "runner_timeout_pid_live": True,
            "runner_timeout_client_live": True,
            "runner_timeout_client_ancestry_match": True,
        }
        failed_prompt = {"argv": ["run", "secret", "./secret.sh"], "exit_code": 7}
        self.assertIsNone(eval_run.s05_handoff_call([failed_prompt, interrupted_wait]))

    def test_process_ancestry_uses_live_os_parentage(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        self.addCleanup(child.kill)
        try:
            self.assertTrue(eval_run.process_descends_from(child.pid, os.getpid()))
            self.assertFalse(eval_run.process_descends_from(child.pid, 999_999_999))
        finally:
            child.kill()
            child.wait(timeout=5)

    def test_supported_repl_and_server_launch_forms_prove_calls(self) -> None:
        repl_calls = [
            {"argv": ["new", "--name", "py"], "exit_code": 0},
            {"argv": ["run", "py", "python3", "--timeout", "10s"], "exit_code": 0},
            {"argv": ["send", "py", "--text", "1234 * 5678", "--enter"], "exit_code": 0},
            {"argv": ["send", "py", "--text", "exit()", "--enter"], "exit_code": 0},
        ]
        self.assertEqual(eval_run.validate_scenario_calls("S06", repl_calls), [])

        server_calls = [
            {"argv": ["new", "--name", "server", "--cmd", "./server.sh"], "exit_code": 0},
            {"argv": ["new", "--name", "client", "--cmd", "./hit.sh"], "exit_code": 0},
            {"argv": ["log", "server"], "exit_code": 0},
        ]
        self.assertEqual(eval_run.validate_scenario_calls("S08", server_calls), [])

        disconnected_server_calls = [
            {
                "argv": ["run", "server", "./server.sh"],
                "exit_code": -15,
                "exit_signal": 15,
                "received_signals": [15],
                "cancel_reason": "client-disconnected",
                "client_connected_at_finish": False,
            },
            {"argv": ["run", "client", "./hit.sh"], "exit_code": 0},
            {"argv": ["peek", "server"], "exit_code": 0},
        ]
        self.assertEqual(
            eval_run.validate_scenario_calls("S08", disconnected_server_calls), []
        )
        disconnected_server_calls[0]["cancel_reason"] = "broker-finalize"
        self.assertTrue(
            eval_run.validate_scenario_calls("S08", disconnected_server_calls)
        )

    def test_s08_accepts_status_filter_but_rejects_unrelated_log_filter(self) -> None:
        calls = [
            {"argv": ["new", "--name", "server"], "exit_code": 0},
            {
                "argv": ["run", "server", "./server.sh", "--timeout", "5s"],
                "exit_code": 0,
            },
            {"argv": ["new", "--name", "client"], "exit_code": 0},
            {
                "argv": ["run", "client", "./hit.sh", "--timeout", "10s"],
                "exit_code": 0,
            },
            {"argv": ["log", "server", "--grep", "200"], "exit_code": 0},
        ]
        self.assertEqual(eval_run.validate_scenario_calls("S08", calls), [])
        calls[-1] = {"argv": ["log", "server", "--grep", "PORT"], "exit_code": 0}
        self.assertTrue(eval_run.validate_scenario_calls("S08", calls))
        calls[-1] = {"argv": ["log", "server", "--grep", "2000"], "exit_code": 0}
        self.assertTrue(eval_run.validate_scenario_calls("S08", calls))
        calls[-1] = {"argv": ["peek", "server"], "exit_code": 0}
        self.assertEqual(eval_run.validate_scenario_calls("S08", calls), [])
        calls[-1] = {"argv": ["peek", "server", "--screen"], "exit_code": 0}
        self.assertTrue(eval_run.validate_scenario_calls("S08", calls))
        calls[-1] = {"argv": ["peek", "client"], "exit_code": 0}
        self.assertTrue(eval_run.validate_scenario_calls("S08", calls))

    def test_s09_requires_in_place_interrupt_before_recovery(self) -> None:
        recovered_in_place = [
            {"argv": ["send", "worker", "--key", "C-c"], "exit_code": 0},
            {
                "argv": ["run", "worker", "echo WORKER-RECOVERED"],
                "exit_code": 0,
            },
        ]
        self.assertEqual(
            eval_run.validate_scenario_calls("S09", recovered_in_place), []
        )
        replaced_terminal = [
            {"argv": ["kill", "worker"], "exit_code": 0},
            {"argv": ["new", "--name", "worker"], "exit_code": 0},
            {
                "argv": ["run", "worker", "echo WORKER-RECOVERED"],
                "exit_code": 0,
            },
        ]
        self.assertTrue(eval_run.validate_scenario_calls("S09", replaced_terminal))

    def test_canonical_skill_promotes_in_place_hung_recovery(self) -> None:
        skill = (eval_run.SKILL_SOURCE / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("pairmux send <name> --key C-c", skill)
        self.assertIn("pairmux wait <name> --idle 800", skill)
        self.assertIn("`kill` destroys the terminal", skill)
        self.assertIn("Pattern waits observe future output only", skill)
        self.assertIn("use `peek`/`log --grep`; never wait for a past line", skill)

    def test_sourcing_generated_env_preserves_broker_proxy(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "source_env"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "source-env-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_root, result = self.result_for(completed)
        calls = [
            json.loads(line)
            for line in (run_root / result["paths"]["pairmux_calls"])
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual([call["argv"][0] for call in calls], ["new", "run"])
        self.assertEqual(result["trace_validation_errors"], [])

    def test_marker_shortcuts_fail_exact_call_validation(self) -> None:
        cases = {
            "S01": [{"argv": ["run", "t", "echo PAIRMUX-S01-OK"], "exit_code": 1}],
            "S03": [{"argv": ["run", "t", "cat haystack.log"], "exit_code": 0}],
            "S06": [
                {"argv": ["new", "--name", "py", "--cmd", "python3"], "exit_code": 0},
                {"argv": ["send", "py", "--text", "1234 * 5678", "--enter"], "exit_code": 0},
            ],
            "S08": [
                {"argv": ["run", "same", "./server.sh"], "exit_code": 0},
                {"argv": ["run", "same", "./hit.sh"], "exit_code": 0},
                {"argv": ["log", "same", "--grep", "GET"], "exit_code": 0},
            ],
            "S10": [{"argv": ["run", "x", "printf ZT-9QK > token.txt"], "exit_code": 0}],
        }
        for scenario, calls in cases.items():
            with self.subTest(scenario=scenario):
                self.assertTrue(eval_run.validate_scenario_calls(scenario, calls))

    def test_failed_proxy_calls_do_not_prove_scenarios(self) -> None:
        cases = {
            "S03": [
                {"argv": ["run", "log", "cat haystack.log"], "exit_code": 0},
                {"argv": ["log", "log", "--grep", "FATAL|E4231"], "exit_code": 7},
            ],
            "S04": [
                {"argv": ["run", "prompt", "./confirm.sh"], "exit_code": 0},
                {"argv": ["send", "prompt", "--text", "yes", "--enter"], "exit_code": 7},
            ],
            "S06": [
                {"argv": ["new", "--name", "py", "--cmd", "python3"], "exit_code": 0},
                {"argv": ["send", "py", "--text", "1234 * 5678", "--enter"], "exit_code": 0},
                {"argv": ["send", "py", "--text", "exit()", "--enter"], "exit_code": 7},
            ],
            "S07": [{"argv": ["send", "report", "--text", "q"], "exit_code": 7}],
            "S08": [
                {"argv": ["run", "server", "./server.sh"], "exit_code": 0},
                {"argv": ["run", "client", "./hit.sh"], "exit_code": 0},
                {"argv": ["log", "server", "--grep", "GET|HTTP"], "exit_code": 7},
            ],
            "S09": [
                {"argv": ["send", "worker", "--key", "C-c"], "exit_code": 7},
                {"argv": ["run", "worker", "echo WORKER-RECOVERED"], "exit_code": 0},
            ],
            "S10": [{"argv": ["peek", "handoff"], "exit_code": 7}],
        }
        for scenario, calls in cases.items():
            with self.subTest(scenario=scenario):
                self.assertTrue(eval_run.validate_scenario_calls(scenario, calls))

    def test_broker_rejects_client_reported_evidence_and_does_not_scan_agent_files(self) -> None:
        runtime = Path(tempfile.mkdtemp(prefix="pmx-forge-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, runtime, True)
        real = runtime / "real-pairmux"
        shutil.copy2(self.bin_dir / "pairmux", real)
        real.chmod(0o755)
        broker = eval_run.PairmuxBroker(
            runtime / "broker.sock",
            real_pairmux=real,
            real_pairmux_sha256=eval_run.sha256_file(real),
            fixed_env=self.env,
            allowed_cwd=self.root,
            expected_socket="forge-test",
        )
        broker.start()
        invalid = json.dumps(
            {
                "schema": "pairmux.eval.call.v1",
                "argv": ["wait", "fake", "--human"],
                "cwd": str(self.root),
                "exit_code": 0,
                "pid": os.getpid(),
            }
        ).encode()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(runtime / "broker.sock"))
                client.sendall(struct.pack("!I", len(invalid)) + invalid)
                client.shutdown(socket.SHUT_WR)
                client.recv(4096)
        finally:
            trace = broker.stop_and_finalize()
        self.assertEqual(trace.calls, [])
        self.assertTrue(trace.errors)
        self.assertEqual(trace.rejections, [])

        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "forge_trace_file"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "forge-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        _run_root, result = self.result_for(completed)
        self.assertEqual(result["steps"], 2)

    def test_broker_protocol_error_fails_episode_even_after_real_calls(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "forge_broker_evidence"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "broker-protocol-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        _run_root, result = self.result_for(completed)
        self.assertEqual(result["steps"], 2)
        self.assertIn("broker protocol error", " ".join(result["trace_validation_errors"]))

    def test_broker_audits_out_of_root_cwd_and_allows_recovery(self) -> None:
        runtime = Path(tempfile.mkdtemp(prefix="pmx-policy-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, runtime, True)
        proxy = runtime / "bin" / "pairmux"
        proxy.parent.mkdir(parents=True)
        shutil.copy2(EVALS_DIR / "pairmux_proxy.py", proxy)
        proxy.chmod(0o755)
        real = runtime / "real-pairmux"
        shutil.copy2(self.bin_dir / "pairmux", real)
        real.chmod(0o755)
        allowed = self.root / "allowed"
        outside = self.root / "outside"
        allowed.mkdir()
        outside.mkdir()
        broker = eval_run.PairmuxBroker(
            runtime / "broker.sock",
            real_pairmux=real,
            real_pairmux_sha256=eval_run.sha256_file(real),
            fixed_env=self.env,
            allowed_cwd=allowed,
            expected_socket="policy-test",
        )
        with self.assertRaisesRegex(ValueError, "must be absolute"):
            broker._validated_cwd(".")
        broker.start()
        try:
            denied = subprocess.run(
                [str(proxy), "mock-fail"],
                cwd=outside,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            recovered = subprocess.run(
                [str(proxy), "mock-fail"],
                cwd=allowed,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        finally:
            trace = broker.stop_and_finalize()
        self.assertEqual(denied.returncode, 125)
        self.assertIn("cwd escapes", denied.stderr)
        self.assertEqual(recovered.returncode, 23)
        self.assertEqual(trace.errors, [])
        self.assertEqual(len(trace.calls), 1)
        self.assertEqual(len(trace.rejections), 1)
        rejection = trace.rejections[0]
        self.assertEqual(rejection["schema"], eval_run.BROKER_REJECTION_SCHEMA)
        self.assertEqual(rejection["code"], "cwd-outside-work-root")
        self.assertEqual(Path(rejection["requested_cwd"]).resolve(), outside.resolve())
        self.assertEqual(rejection["argv"], ["mock-fail"])

    def test_broker_keeps_socket_override_fatal_for_out_of_root_cwd(self) -> None:
        runtime = Path(tempfile.mkdtemp(prefix="pmx-policy-order-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, runtime, True)
        proxy = runtime / "bin" / "pairmux"
        proxy.parent.mkdir(parents=True)
        shutil.copy2(EVALS_DIR / "pairmux_proxy.py", proxy)
        proxy.chmod(0o755)
        real = runtime / "real-pairmux"
        shutil.copy2(self.bin_dir / "pairmux", real)
        real.chmod(0o755)
        allowed = self.root / "fatal-allowed"
        outside = self.root / "fatal-outside"
        allowed.mkdir()
        outside.mkdir()
        broker = eval_run.PairmuxBroker(
            runtime / "broker.sock",
            real_pairmux=real,
            real_pairmux_sha256=eval_run.sha256_file(real),
            fixed_env=self.env,
            allowed_cwd=allowed,
            expected_socket="expected-socket",
        )
        broker.start()
        try:
            completed = subprocess.run(
                [str(proxy), "--socket", "forged-socket", "ls"],
                cwd=outside,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        finally:
            trace = broker.stop_and_finalize()
        self.assertEqual(completed.returncode, 125)
        self.assertEqual(trace.calls, [])
        self.assertEqual(trace.rejections, [])
        self.assertIn("overrides the episode pairmux socket", " ".join(trace.errors))

    def test_episode_audits_policy_rejection_then_passes_on_real_calls(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "policy_rejection_then_pass"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "policy-recovery-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_root, result = self.result_for(completed)
        self.assertTrue(result["pass"])
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["broker_policy_rejections"], 1)
        self.assertEqual(result["trace_validation_errors"], [])
        rejections = [
            json.loads(line)
            for line in (run_root / result["paths"]["broker_rejections"])
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0]["code"], "cwd-outside-work-root")
        self.assertFalse(rejections[0]["executed"])
        self.assertTrue(Path(rejections[0]["resolved_cwd"]).is_absolute())
        self.assertTrue(Path(rejections[0]["allowed_cwd"]).is_absolute())
        summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["totals"]["broker_policy_rejections"], 1)
        self.assertEqual(summary["scenarios"]["S01"]["broker_policy_rejections"], 1)
        self.assertIn(
            "Broker policy rejections: 1",
            (run_root / "summary.md").read_text(encoding="utf-8"),
        )

    def test_agent_environment_and_control_assets_are_isolated(self) -> None:
        host_home = self.root / "host-home"
        (host_home / ".config/opencode/skills/pairmux").mkdir(parents=True)
        (host_home / ".config/opencode/skills/pairmux/SKILL.md").write_text(
            "host poison", encoding="utf-8"
        )
        env = self.env.copy()
        env.update(
            {
                "HOME": str(host_home),
                "XDG_CONFIG_HOME": str(host_home / ".config"),
                "OPENCODE_CONFIG_DIR": str(host_home / ".config/opencode"),
                "PAIRMUX_HOST_POISON": "must-not-pass",
            }
        )
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "isolated-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_root, result = self.result_for(completed)
        invocation = json.loads(self.agent_log.read_text(encoding="utf-8").splitlines()[0])
        self.assertNotEqual(Path(invocation["home"]), host_home)
        self.assertIsNone(invocation["host_poison"])
        self.assertIsNone(invocation["real_bin_exposed"])
        work = run_root / result["paths"]["episode"] / "work/S01"
        for name in ("setup.sh", "check.sh", "env.sh", "lib.sh"):
            self.assertFalse((work / name).exists(), name)
        manifest = json.loads(
            (run_root / result["paths"]["control_manifest"]).read_text(encoding="utf-8")
        )
        self.assertFalse(manifest["host_home_inherited"])
        self.assertEqual(manifest["proxy_trace_transport"], "runner-owned-execution-broker")
        self.assertTrue(manifest["broker_ledger_serialized_after_agent"])
        self.assertFalse(manifest["broker_request_can_report_evidence"])
        self.assertTrue(manifest["broker_denied_cwd_requests_are_audited"])
        self.assertEqual(
            manifest["nonfatal_broker_policy_rejection_codes"],
            ["cwd-outside-work-root"],
        )
        self.assertEqual(
            manifest["agent_project_isolation"]["method"],
            "nested-committed-git-root",
        )

    def test_s10_accepts_exact_token_with_optional_single_newline(self) -> None:
        cases = (
            (b"ZT-9QK", 0),
            (b"ZT-9QK\n", 0),
            (b"ZT-9QK\n\n", 1),
            (b"ZT-9QK\r\n", 1),
            (b"ZT-9QK ", 1),
        )
        for index, (content, expected) in enumerate(cases):
            with self.subTest(content=content):
                scenario_dir = eval_run.copy_scenario(
                    "S10", self.root / f"s10-check-{index}"
                )
                state_dir = scenario_dir / "state"
                terminal_dir = state_dir / "handoff"
                terminal_dir.mkdir(parents=True)
                (terminal_dir / "index.jsonl").write_text(
                    '{"text":"ZT-9QK"}\n', encoding="utf-8"
                )
                (scenario_dir / "token.txt").write_bytes(content)
                env_file = scenario_dir / "env.sh"
                env_file.touch()
                proof_path = scenario_dir / "trace-proof.json"
                eval_run.atomic_json(
                    proof_path,
                    {
                        "schema": "pairmux.eval.trace-proof.v1",
                        "scenario": "S10",
                        "valid": True,
                        "errors": [],
                    },
                )
                env = self.env.copy()
                env.update(
                    {
                        "PAIRMUX_EVAL_SCENARIO_DIR": str(scenario_dir),
                        "PAIRMUX_EVAL_ENV_FILE": str(env_file),
                        "PAIRMUX_EVAL_TRACE_PROOF": str(proof_path),
                        "PAIRMUX_STATE_DIR": str(state_dir),
                    }
                )
                completed = subprocess.run(
                    [str(scenario_dir / "check.sh")],
                    cwd=scenario_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(completed.returncode, expected, completed.stderr)
                if expected:
                    self.assertIn("token.txt must contain exactly", completed.stderr)

    def test_s08_check_requires_agent_to_report_the_request_line(self) -> None:
        scenario_dir = eval_run.copy_scenario("S08", self.root / "s08-check")
        state_dir = scenario_dir / "state"
        server_dir = state_dir / "server"
        client_dir = state_dir / "client"
        server_dir.mkdir(parents=True)
        client_dir.mkdir(parents=True)
        (server_dir / "raw.log").write_text(
            '127.0.0.1 - - "GET / HTTP/1.1" 200 -\n', encoding="utf-8"
        )
        (client_dir / "raw.log").write_text("HTTP-STATUS=200\n", encoding="utf-8")
        env_file = scenario_dir / "env.sh"
        env_file.touch()
        proof_path = scenario_dir / "trace-proof.json"
        eval_run.atomic_json(
            proof_path,
            {
                "schema": "pairmux.eval.trace-proof.v1",
                "scenario": "S08",
                "valid": True,
                "errors": [],
            },
        )
        transcript = scenario_dir / "transcript.txt"
        env = self.env.copy()
        env.update(
            {
                "PAIRMUX_EVAL_SCENARIO_DIR": str(scenario_dir),
                "PAIRMUX_EVAL_ENV_FILE": str(env_file),
                "PAIRMUX_EVAL_TRACE_PROOF": str(proof_path),
                "PAIRMUX_STATE_DIR": str(state_dir),
                "PAIRMUX_STATE_NAMESPACE": "",
            }
        )
        transcript.write_text(
            'Request: "GET / HTTP/1.1" 200 -\n', encoding="utf-8"
        )
        reported = subprocess.run(
            [str(scenario_dir / "check.sh"), str(transcript)],
            cwd=scenario_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        self.assertEqual(reported.returncode, 0, reported.stderr)

        transcript.write_text("The status was 200.\n", encoding="utf-8")
        omitted = subprocess.run(
            [str(scenario_dir / "check.sh"), str(transcript)],
            cwd=scenario_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        self.assertEqual(omitted.returncode, 1)
        self.assertIn("did not report", omitted.stderr)

    def test_skill_tampering_fails_closed(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "mutate_skill"
        completed = self.invoke(
            "--agent",
            "claude",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "skill-tamper-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        _run_root, result = self.result_for(completed)
        self.assertIn("installed skill changed", " ".join(result["trace_validation_errors"]))

    def test_acceptance_metadata_is_explicit_and_fail_closed(self) -> None:
        completed = self.invoke(
            "--agent",
            "codex",
            "--provider",
            "openai",
            "--model",
            "mock-model",
            "--acceptance-profile",
            "p4",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "acceptance-runs"),
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        run_root, result = self.result_for(completed)
        summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(result["provider"], "openai")
        self.assertTrue(result["provider_verified"])
        self.assertIn("commit", result["git"])
        self.assertIn("TASK.md", result["scenario_source_sha256"])
        self.assertFalse(summary["acceptance"]["eligible"])
        self.assertEqual(summary["acceptance"]["pass_rate_threshold"], 1.0)
        self.assertIn("Acceptance eligible: **false**", (run_root / "summary.md").read_text())

    def test_provider_and_model_values_are_validated(self) -> None:
        for arguments in (
            ("--provider", " "),
            ("--model", " "),
            ("--provider", "openai", "--model", "opencode/big-pickle"),
        ):
            with self.subTest(arguments=arguments):
                completed = self.invoke(
                    "--agent",
                    "opencode",
                    "--dry-run",
                    *arguments,
                )
                self.assertEqual(completed.returncode, 2)

    def test_acceptance_requires_stable_git_provenance(self) -> None:
        results = [
            {"scenario": f"S{number:02d}", "pass": True}
            for number in range(1, 11)
            for _repeat in range(3)
        ]
        accepted = eval_run.acceptance_status(
            profile="p4",
            agent="opencode",
            provider_verified=True,
            model_verified=True,
            results=results,
            git={"commit": "a" * 40, "dirty": False, "stable": True},
        )
        self.assertTrue(accepted["eligible"])
        for git in (
            {"commit": None, "dirty": False, "stable": True},
            {"commit": "a" * 40, "dirty": False, "stable": False},
        ):
            with self.subTest(git=git):
                rejected = eval_run.acceptance_status(
                    profile="p4",
                    agent="opencode",
                    provider_verified=True,
                    model_verified=True,
                    results=results,
                    git=git,
                )
                self.assertFalse(rejected["eligible"])

    def test_acceptance_rejects_contradictory_provider_failure(self) -> None:
        results = [
            {"scenario": f"S{number:02d}", "pass": True, "failure_class": None}
            for number in range(1, 11)
            for _repeat in range(3)
        ]
        results[0]["failure_class"] = "provider_rate_limited"
        rejected = eval_run.acceptance_status(
            profile="p4",
            agent="opencode",
            provider_verified=True,
            model_verified=True,
            results=results,
            git={"commit": "a" * 40, "dirty": False, "stable": True},
        )
        self.assertFalse(rejected["eligible"])
        self.assertIn("S01 pass rate", " ".join(rejected["reasons"]))

    def test_check_helpers_find_custom_socket_hashed_state(self) -> None:
        state = self.root / "state"
        socket_name = "isolated-test-socket"
        tmux_root = self.root / "tmux-root"
        tmux_root.mkdir()
        identity = os.path.join(str(tmux_root.resolve()), f"tmux-{os.getuid()}", socket_name)
        digest = hashlib.sha256(identity.encode()).hexdigest()
        terminal = state / ".sockets" / digest / "worker"
        terminal.mkdir(parents=True)
        (terminal / "raw.log").write_text("HASHED-MARKER\n", encoding="utf-8")
        env = self.env.copy()
        env.pop("PAIRMUX_STATE_NAMESPACE", None)
        env.update(
            {
                "PAIRMUX_STATE_DIR": str(state),
                "PAIRMUX_SOCKET": socket_name,
                "TMUX_TMPDIR": str(tmux_root),
            }
        )
        completed = subprocess.run(
            [
                "bash",
                "-c",
                '. "$1"; pmx_journal_has worker HASHED-MARKER',
                "bash",
                str(EVALS_DIR / "lib.sh"),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_codex_json_scoping_excludes_aggregated_output(self) -> None:
        transcript = self.root / "codex.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "command_execution",
                                "command": "pairmux wait secret --human --notify",
                                "aggregated_output": "hunter2-correct",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "agent_message", "text": "handoff requested"},
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                "bash",
                "-c",
                '. "$1"; pmx_issued_content "$2"',
                "bash",
                str(EVALS_DIR / "lib.sh"),
                str(transcript),
            ],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("pairmux wait secret --human --notify", completed.stdout)
        self.assertIn("handoff requested", completed.stdout)
        self.assertNotIn("hunter2-correct", completed.stdout)


if __name__ == "__main__":
    unittest.main()
