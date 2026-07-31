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
from unittest import mock


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
        self.version_log = self.root / "version.jsonl"
        self.env = os.environ.copy()
        self.env.update(
            {
                "PATH": str(self.bin_dir) + os.pathsep + self.env.get("PATH", ""),
                "PAIRMUX_MOCK_AGENT_LOG": str(self.agent_log),
                "PAIRMUX_MOCK_VERSION_LOG": str(self.version_log),
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
        available = {
            ("S", 1): "S01",
            ("S", 2): "S02",
            ("S", 3): "S03",
            ("S", 6): "S06",
            ("M", 1): "M01",
            ("M", 2): "M02",
            ("M", 3): "M03",
        }
        self.assertEqual(eval_run.parse_scenarios(["S01-S03", "6", "S02"], available), ["S01", "S02", "S03", "S06"])
        self.assertEqual(eval_run.parse_scenarios(["M01,M03"], available), ["M01", "M03"])
        self.assertEqual(eval_run.parse_scenarios(["M1-M3"], available), ["M01", "M02", "M03"])
        # Bare numbers stay S-suite selectors; the default order is S then M.
        self.assertEqual(eval_run.parse_scenarios(["1"], available), ["S01"])
        self.assertEqual(
            eval_run.parse_scenarios(None, available),
            ["S01", "S02", "S03", "S06", "M01", "M02", "M03"],
        )
        with self.assertRaisesRegex(ValueError, "ascending"):
            eval_run.parse_scenarios(["S03-S01"], available)
        with self.assertRaisesRegex(ValueError, "unknown"):
            eval_run.parse_scenarios(["S04"], available)
        with self.assertRaisesRegex(ValueError, "mix suites"):
            eval_run.parse_scenarios(["S01-M03"], available)

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

    def test_version_probes_use_secret_free_ephemeral_environment(self) -> None:
        secret = "version-probe-hf-secret-sentinel-8d31"
        env = self.env.copy()
        env.update(
            {
                "HF_TOKEN": secret,
                "OPENAI_API_KEY": "version-openai-secret",
                "ANTHROPIC_API_KEY": "version-anthropic-secret",
                "OPENCODE_AUTH_CONTENT": "version-opencode-content-secret",
                "OPENCODE_API_KEY": "version-opencode-key-secret",
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
            str(self.root / "version-probe-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_root, result = self.result_for(completed)
        records = [
            json.loads(line)
            for line in self.version_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual({record["program"] for record in records}, {"opencode", "pairmux"})
        self.assertTrue(all(record["credential_names_present"] == [] for record in records))
        probe_homes = {Path(record["home"]) for record in records}
        self.assertEqual(len(probe_homes), 1)
        probe_home = next(iter(probe_homes))
        self.assertTrue(
            all(Path(record["cwd"]).resolve() == probe_home.resolve() for record in records)
        )
        self.assertFalse(probe_home.exists())
        self.assertEqual(result["agent_version"], "opencode mock-1.0")
        self.assertEqual(result["pairmux_version"], "pairmux mock-1.0")
        persisted = b"\n".join(
            path.read_bytes() for path in run_root.rglob("*") if path.is_file()
        )
        self.assertNotIn(secret.encode(), persisted)
        self.assertNotIn(secret, completed.stdout)
        self.assertNotIn(secret, completed.stderr)

    def test_git_provenance_uses_secret_free_environment(self) -> None:
        revision = subprocess.CompletedProcess(
            ["git"], 0, stdout="a" * 40 + "\n", stderr=""
        )
        status = subprocess.CompletedProcess(["git"], 0, stdout="", stderr="")
        poisoned = {
            "PATH": self.env.get("PATH", ""),
            "HF_TOKEN": "hf-secret",
            "OPENAI_API_KEY": "openai-secret",
            "ANTHROPIC_API_KEY": "anthropic-secret",
            "OPENCODE_AUTH_CONTENT": "opencode-secret",
        }
        with (
            mock.patch.dict(os.environ, poisoned, clear=True),
            mock.patch.object(eval_run.subprocess, "run", side_effect=(revision, status)) as run,
        ):
            provenance = eval_run.git_provenance(self.root)
        self.assertEqual(provenance, {"commit": "a" * 40, "dirty": False})
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            child_env = call.kwargs["env"]
            self.assertEqual(child_env["PATH"], poisoned["PATH"])
            self.assertEqual(child_env["GIT_CONFIG_GLOBAL"], os.devnull)
            for name in (
                "HF_TOKEN",
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "OPENCODE_AUTH_CONTENT",
            ):
                self.assertNotIn(name, child_env)

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
            "1",
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

    def test_huggingface_provider_failures_are_classified_and_stop_schedule(self) -> None:
        expected = {
            "huggingface_rate_limited": "provider_rate_limited",
            "huggingface_auth_failed": "provider_auth_failed",
            "huggingface_unavailable": "provider_unavailable",
        }
        for mode, failure_class in expected.items():
            with self.subTest(mode=mode):
                env = self.env.copy()
                env["PAIRMUX_MOCK_MODE"] = mode
                env["HF_TOKEN"] = "mock-hf-token"
                completed = self.invoke(
                    "--agent",
                    "opencode",
                    "--provider",
                    "huggingface",
                    "--model",
                    "huggingface/deepseek-ai/DeepSeek-V4-Flash",
                    "--opencode-auth-env",
                    "HF_TOKEN",
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
                self.assertEqual(result["failure_class"], failure_class)
                self.assertEqual(result["agent_observed_failure_class"], failure_class)
                self.assertFalse(result["timed_out"])
                self.assertEqual(
                    result["credential_injection"]["method"],
                    "isolated-auth-file-from-environment",
                )
                summary = json.loads(
                    (run_root / "summary.json").read_text(encoding="utf-8")
                )
                self.assertEqual(summary["stop_reason"], failure_class)
                self.assertEqual(summary["schedule"]["completed_episodes"], 1)
                self.assertEqual(summary["schedule"]["skipped_episodes"], 1)

    def test_huggingface_machine_log_variants_are_classified_narrowly(self) -> None:
        prefix = (
            'timestamp=2026-07-19T00:00:00Z level=ERROR message="stream error" '
            'error.error="'
        )
        cases = {
            "AI_APICallError: Too Many Requests": "provider_rate_limited",
            (
                "AI_RetryError: Failed after 3 attempts. Last error: "
                "Too Many Requests statusCode: 429"
            ): "provider_rate_limited",
            "AI_APICallError: Unauthorized": "provider_auth_failed",
            "AI_APICallError: Invalid username or password": "provider_auth_failed",
            "AI_APICallError: Forbidden": "provider_auth_failed",
            "AI_APICallError: Internal Server Error": "provider_unavailable",
            "AI_APICallError: Service Unavailable": "provider_unavailable",
            (
                "AI_RetryError: Failed after 3 attempts. Last error: "
                "Gateway Timeout statusCode: 504"
            ): "provider_unavailable",
        }
        for error_text, failure_class in cases.items():
            with self.subTest(error_text=error_text):
                self.assertEqual(
                    eval_run.opencode_provider_failure(prefix + error_text + '"'),
                    failure_class,
                )

        for stderr in (
            prefix + 'AI_APICallError: Bad Request statusCode: 400"',
            prefix + 'AI_APICallError: Not Found statusCode: 404"',
            prefix + 'ProviderModelNotFoundError: Model not found"',
            'level=ERROR message="other error" error.error="AI_APICallError: Unauthorized"',
            'message="stream error" error.error="AI_APICallError: Too Many Requests"',
        ):
            with self.subTest(stderr=stderr):
                self.assertIsNone(eval_run.opencode_provider_failure(stderr))

    def test_opencode_silent_hang_remains_agent_timeout(self) -> None:
        env = self.env.copy()
        env["PAIRMUX_MOCK_MODE"] = "hang"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "1",
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
            "2",
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
            "3",
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
        durable_timeouts = (
            ("--timeout=300s",),
            ("-timeout", "5m"),
            ("---timeout=600s",),
            ("--timeout", "4m60s"),
            ("--timeout", "2562047h47m16.854775807s"),
        )
        for timeout_arguments in durable_timeouts:
            with self.subTest(durable_timeout=timeout_arguments):
                durable = dict(proof)
                durable["argv"] = [
                    "wait",
                    "t1",
                    "--human",
                    "--notify",
                    *timeout_arguments,
                ]
                self.assertTrue(
                    eval_run.calls_have_human_wait([durable], require_interrupted=True)
                )
        rejected_timeouts = (
            ("--timeout", "299s"),
            ("-timeout", "299s"),
            ("---timeout=299s",),
            ("--timeout", "4m59s"),
            ("--timeout", "30s"),
            ("--timeout", "invalid"),
            ("--timeout", "300"),
            ("--timeout", "\u0663\u0660\u0660s"),
            ("--timeout", "2562047h47m16.854775808s"),
            ("--timeout", "299.9999999999s.0000000001s"),
            ("--timeout",),
            ("--timeout", "600s", "-timeout", "600s"),
        )
        for timeout_arguments in rejected_timeouts:
            with self.subTest(short_or_invalid_timeout=timeout_arguments):
                short = dict(proof)
                short["argv"] = [
                    "wait",
                    "t1",
                    "--human",
                    "--notify",
                    *timeout_arguments,
                ]
                self.assertFalse(
                    eval_run.calls_have_human_wait([short], require_interrupted=True)
                )

    def test_pairmux_global_parser_matches_cli_order_and_sentinel_semantics(self) -> None:
        cases = (
            (["--json", "wait", "t"], ["wait", "t"], []),
            (["wait", "t", "-json"], ["wait", "t"], []),
            (["---json=ignored", "wait", "t", "--json"], ["wait", "t"], []),
            (
                ["wait", "t", "-socket", "one", "---socket=two"],
                ["wait", "t"],
                ["one", "two"],
            ),
            (["wait", "t", "--socket"], ["wait", "t"], []),
            (
                ["run", "t", "--", "echo", "--json", "--socket", "literal"],
                ["run", "t", "--", "echo", "--json", "--socket", "literal"],
                [],
            ),
            (
                ["--socket", "--", "wait", "t", "--json"],
                ["wait", "t"],
                ["--"],
            ),
            (["wait", "t", "--unknown"], ["wait", "t", "--unknown"], []),
        )
        for argv, expected_rest, expected_sockets in cases:
            with self.subTest(argv=argv):
                rest, sockets = eval_run.strip_pairmux_globals(argv)
                self.assertEqual(rest, expected_rest)
                self.assertEqual(sockets, expected_sockets)

        self.assertEqual(
            eval_run.effective_pairmux_command(
                ["--", "wait", "t", "--human", "--notify", "--json"]
            ),
            ("wait", ["t", "--human", "--notify", "--json"]),
        )
        self.assertEqual(
            eval_run.effective_pairmux_command(
                ["run", "t", "--", "echo", "--json", "--socket", "literal"]
            ),
            ("run", ["t", "--", "echo", "--json", "--socket", "literal"]),
        )

    def test_socket_override_validation_uses_the_shared_global_parser(self) -> None:
        broker = mock.Mock()
        broker.expected_socket = "expected"
        accepted = (
            ["wait", "t"],
            ["--socket", "expected", "wait", "t"],
            ["wait", "t", "-socket", "expected"],
            ["wait", "t", "---socket=expected"],
            ["wait", "t", "--socket", "expected", "-socket=expected"],
            ["wait", "t", "--socket"],
            ["run", "t", "--", "echo", "--socket", "forged"],
        )
        for argv in accepted:
            with self.subTest(accepted=argv):
                eval_run.PairmuxBroker._validate_socket_override(broker, argv)

        rejected = (
            ["--socket", "forged", "wait", "t"],
            ["wait", "t", "--socket", "forged"],
            ["wait", "t", "-socket", "forged"],
            ["wait", "t", "---socket=forged"],
            ["wait", "t", "--socket", "expected", "-socket", "forged"],
            ["wait", "t", "--socket", "--", "echo"],
        )
        for argv in rejected:
            with self.subTest(rejected=argv):
                with self.assertRaisesRegex(ValueError, "overrides"):
                    eval_run.PairmuxBroker._validate_socket_override(broker, argv)

    def test_s05_accepts_durable_retry_after_client_disconnect(self) -> None:
        run_secret = {"argv": ["run", "secret", "./secret.sh"], "exit_code": 0}
        disconnected = {
            "argv": ["wait", "secret", "--human", "--notify"],
            "cancel_reason": "client-disconnected",
            "client_connected_at_finish": False,
            "exit_code": -15,
        }
        durable_retry = {
            "argv": [
                "wait",
                "secret",
                "--human",
                "--notify",
                "--timeout",
                "600s",
                "--json",
            ],
            "runner_timeout_interrupted": True,
            "runner_timeout_pid_live": True,
            "runner_timeout_client_live": True,
            "runner_timeout_client_ancestry_match": True,
        }
        calls = [run_secret, disconnected, durable_retry]
        self.assertIs(eval_run.s05_handoff_call(calls), durable_retry)
        self.assertTrue(eval_run.calls_have_human_wait(calls, require_interrupted=True))

    def test_s05_proof_rejects_early_signal_wrong_terminal_missing_notify_and_short_timeout(self) -> None:
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
            {
                "argv": ["wait", "secret", "--human", "--notify", "--timeout", "invalid"],
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
        self.assertIn("one valid explicit timeout of at least 300s", skill)

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
        forged_argv = (
            ["--socket", "forged-socket", "ls"],
            ["ls", "--socket", "forged-socket"],
            ["ls", "-socket", "forged-socket"],
            ["ls", "---socket=forged-socket"],
        )
        try:
            completed = [
                subprocess.run(
                    [str(proxy), *argv],
                    cwd=outside,
                    env=self.env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                for argv in forged_argv
            ]
        finally:
            trace = broker.stop_and_finalize()
        self.assertTrue(all(result.returncode == 125 for result in completed))
        self.assertEqual(trace.calls, [])
        self.assertEqual(trace.rejections, [])
        self.assertEqual(len(trace.errors), len(forged_argv))
        self.assertTrue(
            all("overrides the episode pairmux socket" in error for error in trace.errors)
        )

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

    def test_explicit_opencode_auth_is_minimized_isolated_and_removed(self) -> None:
        opencode_secret = "zen-secret-sentinel-71d9"
        unrelated_secret = "anthropic-secret-sentinel-2bc4"
        env_secret = "environment-secret-sentinel-5a10"
        auth_file = self.root / "host-auth.json"
        source_payload = {
            "opencode": {
                "type": "api",
                "key": opencode_secret,
                "metadata": {"unneeded": "not-copied"},
            },
            "anthropic": {"type": "api", "key": unrelated_secret},
        }
        auth_file.write_text(json.dumps(source_payload), encoding="utf-8")
        auth_file.chmod(0o600)
        env = self.env.copy()
        env["OPENCODE_AUTH_CONTENT"] = env_secret
        env["OPENCODE_API_KEY"] = env_secret
        completed = self.invoke(
            "--agent",
            "opencode",
            "--provider",
            "opencode",
            "--model",
            "opencode/big-pickle",
            "--opencode-auth-file",
            str(auth_file),
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "explicit-auth-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_root, result = self.result_for(completed)
        invocation = json.loads(self.agent_log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(invocation["opencode_auth_providers"], ["opencode"])
        self.assertEqual(invocation["opencode_auth_mode"], "0o600")
        self.assertFalse(invocation["opencode_auth_content_present"])
        self.assertFalse(invocation["opencode_api_key_present"])
        self.assertFalse(Path(invocation["opencode_auth_path"]).exists())
        self.assertEqual(
            result["credential_injection"],
            {
                "cleanup_verified": True,
                "method": "isolated-auth-file",
                "provider": "opencode",
                "verified": True,
            },
        )
        manifest = json.loads(
            (run_root / result["shell_path_guard"]["artifact"]).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["credential_injection"], result["credential_injection"])
        self.assertEqual(json.loads(auth_file.read_text(encoding="utf-8")), source_payload)

        persisted = b"\n".join(
            path.read_bytes() for path in run_root.rglob("*") if path.is_file()
        )
        console = (completed.stdout + completed.stderr).encode()
        for secret in (opencode_secret, unrelated_secret, env_secret):
            self.assertNotIn(secret.encode(), persisted)
            self.assertNotIn(secret.encode(), console)
        self.assertNotIn(str(auth_file), persisted.decode(errors="replace"))

    def test_explicit_opencode_auth_is_removed_after_agent_timeout_and_error(self) -> None:
        secret = "cleanup-secret-sentinel-a930"
        auth_file = self.root / "cleanup-auth.json"
        auth_file.write_text(
            json.dumps({"opencode": {"type": "api", "key": secret}}),
            encoding="utf-8",
        )
        auth_file.chmod(0o600)
        expected = {"hang": "agent_timeout", "fail": "agent_failed"}
        for mode, failure_class in expected.items():
            with self.subTest(mode=mode):
                self.agent_log.unlink(missing_ok=True)
                env = self.env.copy()
                env["PAIRMUX_MOCK_MODE"] = mode
                completed = self.invoke(
                    "--agent",
                    "opencode",
                    "--provider",
                    "opencode",
                    "--model",
                    "opencode/big-pickle",
                    "--opencode-auth-file",
                    str(auth_file),
                    "--scenario",
                    "S01",
                    "--timeout",
                    "1" if mode == "hang" else "5",
                    "--output-dir",
                    str(self.root / f"auth-{mode}-runs"),
                    env=env,
                )
                self.assertEqual(completed.returncode, 1)
                run_root, result = self.result_for(completed)
                self.assertEqual(result["failure_class"], failure_class)
                self.assertTrue(result["credential_injection"]["cleanup_verified"])
                self.assertIsNone(result["control_cleanup_failure_class"])
                invocation = json.loads(
                    self.agent_log.read_text(encoding="utf-8").splitlines()[0]
                )
                self.assertFalse(Path(invocation["opencode_auth_path"]).exists())
                persisted = b"\n".join(
                    path.read_bytes() for path in run_root.rglob("*") if path.is_file()
                )
                self.assertNotIn(secret.encode(), persisted)

    def test_control_cleanup_failures_are_normalized_and_fatal(self) -> None:
        root = self.root / "credential-cleanup-root"
        credential = root / "home/.local/share/opencode/auth.json"
        credential.parent.mkdir(parents=True)
        credential.write_text("secret", encoding="utf-8")
        with mock.patch.object(Path, "unlink", side_effect=PermissionError("denied")):
            failure = eval_run.cleanup_control_root(root, credential)
        self.assertEqual(failure, "credential_cleanup_failed")
        self.assertFalse(root.exists())

        residual = self.root / "control-cleanup-root"
        residual.mkdir()
        with mock.patch.object(eval_run.shutil, "rmtree", return_value=None):
            failure = eval_run.cleanup_control_root(residual, None)
        self.assertEqual(failure, "control_cleanup_failed")
        self.assertTrue(residual.exists())
        shutil.rmtree(residual)
        self.assertIn("credential_cleanup_failed", eval_run.RUN_FATAL_FAILURE_CLASSES)
        self.assertIn("control_cleanup_failed", eval_run.RUN_FATAL_FAILURE_CLASSES)

    def test_runner_exception_always_cleans_auth_and_cleanup_failure_stops_schedule(self) -> None:
        secret = "runner-cleanup-secret-sentinel-0b42"
        auth_file = self.root / "runner-cleanup-auth.json"
        auth_file.write_text(
            json.dumps({"opencode": {"type": "api", "key": secret}}),
            encoding="utf-8",
        )
        auth_file.chmod(0o600)
        base_arguments = [
            "--agent",
            "opencode",
            "--provider",
            "opencode",
            "--model",
            "opencode/big-pickle",
            "--opencode-auth-file",
            str(auth_file),
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--pairmux-bin",
            str(self.bin_dir / "pairmux"),
        ]

        first_output = self.root / "runner-exception-runs"
        with (
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(
                eval_run,
                "cleanup_tmux",
                side_effect=RuntimeError("simulated runner cleanup failure"),
            ),
            mock.patch("builtins.print"),
        ):
            returncode = eval_run.main(
                [*base_arguments, "--repeat", "1", "--output-dir", str(first_output)]
            )
        self.assertEqual(returncode, 1)
        first_root = next(first_output.iterdir())
        first_result = json.loads(
            (first_root / "results.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual(first_result["failure_class"], "runner_error")
        first_invocation = json.loads(
            self.agent_log.read_text(encoding="utf-8").splitlines()[0]
        )
        first_auth_path = Path(first_invocation["opencode_auth_path"])
        self.assertFalse(first_auth_path.exists())
        self.assertFalse(first_auth_path.parents[4].exists())
        self.assertNotIn(
            secret.encode(),
            b"\n".join(path.read_bytes() for path in first_root.rglob("*") if path.is_file()),
        )

        self.agent_log.unlink()
        original_cleanup = eval_run.cleanup_control_root

        def clean_but_report_failure(control_root: Path, credential_path: Path | None) -> str:
            self.assertIsNone(original_cleanup(control_root, credential_path))
            return "credential_cleanup_failed"

        second_output = self.root / "runner-and-cleanup-exception-runs"
        with (
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(
                eval_run,
                "cleanup_tmux",
                side_effect=RuntimeError("simulated runner cleanup failure"),
            ),
            mock.patch.object(
                eval_run,
                "cleanup_control_root",
                side_effect=clean_but_report_failure,
            ),
            mock.patch("builtins.print"),
        ):
            returncode = eval_run.main(
                [*base_arguments, "--repeat", "3", "--output-dir", str(second_output)]
            )
        self.assertEqual(returncode, 1)
        second_root = next(second_output.iterdir())
        results = [
            json.loads(line)
            for line in (second_root / "results.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["failure_class"], "credential_cleanup_failed")
        self.assertEqual(
            results[0]["control_cleanup_failure_class"], "credential_cleanup_failed"
        )
        second_invocation = json.loads(
            self.agent_log.read_text(encoding="utf-8").splitlines()[0]
        )
        second_auth_path = Path(second_invocation["opencode_auth_path"])
        self.assertFalse(second_auth_path.exists())
        self.assertFalse(second_auth_path.parents[4].exists())
        summary = json.loads((second_root / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(
            summary["schedule"],
            {
                "planned_episodes": 3,
                "completed_episodes": 1,
                "skipped_episodes": 2,
                "stopped_early": True,
                "stop_reason": "credential_cleanup_failed",
            },
        )

    def test_cleanup_failure_stops_before_control_manifest_write(self) -> None:
        auth_file = self.root / "manifest-cleanup-auth.json"
        auth_file.write_text(
            json.dumps({"opencode": {"type": "api", "key": "manifest-cleanup-secret"}}),
            encoding="utf-8",
        )
        auth_file.chmod(0o600)
        original_cleanup = eval_run.cleanup_control_root
        original_atomic_json = eval_run.atomic_json
        manifest_writes = 0

        def clean_but_report_failure(control_root: Path, credential_path: Path | None) -> str:
            self.assertIsNone(original_cleanup(control_root, credential_path))
            return "credential_cleanup_failed"

        def fail_manifest_write(path: Path, payload: object) -> None:
            nonlocal manifest_writes
            if path.name == "control-manifest.json":
                manifest_writes += 1
                raise RuntimeError("simulated manifest write failure")
            original_atomic_json(path, payload)

        output_dir = self.root / "manifest-cleanup-runs"
        with (
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(
                eval_run,
                "cleanup_control_root",
                side_effect=clean_but_report_failure,
            ),
            mock.patch.object(eval_run, "atomic_json", side_effect=fail_manifest_write),
            mock.patch("builtins.print"),
        ):
            returncode = eval_run.main(
                [
                    "--agent",
                    "opencode",
                    "--provider",
                    "opencode",
                    "--model",
                    "opencode/big-pickle",
                    "--opencode-auth-file",
                    str(auth_file),
                    "--scenario",
                    "S01",
                    "--repeat",
                    "3",
                    "--timeout",
                    "5",
                    "--pairmux-bin",
                    str(self.bin_dir / "pairmux"),
                    "--output-dir",
                    str(output_dir),
                ]
            )
        self.assertEqual(returncode, 1)
        self.assertEqual(manifest_writes, 0)
        run_root = next(output_dir.iterdir())
        results = [
            json.loads(line)
            for line in (run_root / "results.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["failure_class"], "credential_cleanup_failed")
        summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["stop_reason"], "credential_cleanup_failed")
        self.assertEqual(summary["schedule"]["completed_episodes"], 1)
        self.assertEqual(summary["schedule"]["skipped_episodes"], 2)

    def test_host_opencode_auth_and_environment_are_not_inherited(self) -> None:
        host_home = self.root / "poisoned-host-home"
        host_auth = host_home / ".local/share/opencode/auth.json"
        host_auth.parent.mkdir(parents=True)
        host_auth.write_text(
            json.dumps({"opencode": {"type": "api", "key": "host-poison-secret"}}),
            encoding="utf-8",
        )
        host_auth.chmod(0o600)
        env = self.env.copy()
        env["HOME"] = str(host_home)
        env["OPENCODE_AUTH_CONTENT"] = "host-content-poison"
        env["OPENCODE_API_KEY"] = "host-key-poison"
        env["HF_TOKEN"] = "host-hf-poison"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "no-auth-inheritance-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        _run_root, result = self.result_for(completed)
        invocation = json.loads(self.agent_log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(invocation["opencode_auth_providers"], [])
        self.assertFalse(invocation["opencode_auth_content_present"])
        self.assertFalse(invocation["opencode_api_key_present"])
        self.assertFalse(invocation["hf_token_present"])
        self.assertEqual(result["credential_injection"]["method"], "none")

    def test_hf_token_is_not_part_of_any_base_isolated_environment(self) -> None:
        source = {"PATH": self.env.get("PATH", ""), "HF_TOKEN": "must-not-pass-through"}
        for agent in ("opencode", "claude", "codex"):
            with self.subTest(agent=agent):
                clean = eval_run.isolated_agent_env(
                    source,
                    agent=agent,
                    isolated_home=self.root / f"isolated-{agent}",
                )
                self.assertNotIn("HF_TOKEN", clean)

    def test_huggingface_token_is_isolated_without_runner_persistence(self) -> None:
        secret = "hf-secret-sentinel-d7a4"
        env = self.env.copy()
        env["HF_TOKEN"] = secret
        completed = self.invoke(
            "--agent",
            "opencode",
            "--provider",
            "huggingface",
            "--model",
            "huggingface/deepseek-ai/DeepSeek-V4-Flash",
            "--opencode-auth-env",
            "HF_TOKEN",
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "huggingface-token-runs"),
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_root, result = self.result_for(completed)
        invocation = json.loads(self.agent_log.read_text(encoding="utf-8").splitlines()[0])
        self.assertFalse(invocation["hf_token_present"])
        self.assertEqual(invocation["opencode_auth_providers"], ["huggingface"])
        self.assertEqual(invocation["opencode_auth_mode"], "0o600")
        self.assertFalse(Path(invocation["opencode_auth_path"]).exists())
        self.assertEqual(result["provider"], "huggingface")
        self.assertTrue(result["provider_verified"])
        self.assertEqual(
            result["model"], "huggingface/deepseek-ai/DeepSeek-V4-Flash"
        )
        self.assertEqual(
            result["credential_injection"],
            {
                "cleanup_verified": True,
                "method": "isolated-auth-file-from-environment",
                "provider": "huggingface",
                "verified": True,
            },
        )
        manifest = json.loads(
            (run_root / result["paths"]["control_manifest"]).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["credential_injection"], result["credential_injection"])
        summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(
            summary["results"][0]["credential_injection"],
            result["credential_injection"],
        )
        persisted = b"\n".join(
            path.read_bytes() for path in run_root.rglob("*") if path.is_file()
        )
        self.assertNotIn(secret.encode(), persisted)
        self.assertNotIn(secret, completed.stdout)
        self.assertNotIn(secret, completed.stderr)

    def test_huggingface_auth_file_is_minimized_and_isolated(self) -> None:
        secret = "hf-file-secret-sentinel-1e83"
        unrelated_secret = "unrelated-file-secret-sentinel-6c92"
        auth_file = self.root / "huggingface-auth.json"
        auth_file.write_text(
            json.dumps(
                {
                    "huggingface": {"type": "api", "key": secret},
                    "openai": {"type": "api", "key": unrelated_secret},
                }
            ),
            encoding="utf-8",
        )
        auth_file.chmod(0o600)
        completed = self.invoke(
            "--agent",
            "opencode",
            "--provider",
            "huggingface",
            "--model",
            "huggingface/deepseek-ai/DeepSeek-V4-Flash",
            "--opencode-auth-file",
            str(auth_file),
            "--scenario",
            "S01",
            "--timeout",
            "5",
            "--output-dir",
            str(self.root / "huggingface-auth-file-runs"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        run_root, result = self.result_for(completed)
        invocation = json.loads(self.agent_log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(invocation["opencode_auth_providers"], ["huggingface"])
        self.assertEqual(invocation["opencode_auth_mode"], "0o600")
        self.assertFalse(invocation["hf_token_present"])
        self.assertFalse(Path(invocation["opencode_auth_path"]).exists())
        self.assertEqual(result["provider"], "huggingface")
        self.assertEqual(
            result["model"], "huggingface/deepseek-ai/DeepSeek-V4-Flash"
        )
        self.assertEqual(result["credential_injection"]["method"], "isolated-auth-file")
        self.assertEqual(result["credential_injection"]["provider"], "huggingface")
        self.assertTrue(result["credential_injection"]["cleanup_verified"])
        self.assertEqual(
            json.loads(auth_file.read_text(encoding="utf-8"))["huggingface"]["key"],
            secret,
        )
        persisted = b"\n".join(
            path.read_bytes() for path in run_root.rglob("*") if path.is_file()
        )
        for value in (secret, unrelated_secret, str(auth_file)):
            self.assertNotIn(value.encode(), persisted)
            self.assertNotIn(value, completed.stdout)
            self.assertNotIn(value, completed.stderr)

    def test_opencode_auth_cli_and_source_validation_fail_closed(self) -> None:
        valid = self.root / "valid-auth.json"
        valid.write_text(
            json.dumps({"opencode": {"type": "api", "key": "valid-secret"}}),
            encoding="utf-8",
        )
        valid.chmod(0o600)

        semantic_cases = (
            ("--agent", "claude", "--model", "anthropic/mock", "--opencode-auth-file", str(valid)),
            ("--agent", "opencode", "--opencode-auth-file", str(valid)),
            ("--agent", "claude", "--model", "anthropic/mock", "--opencode-auth-env", "HF_TOKEN"),
            ("--agent", "opencode", "--opencode-auth-env", "HF_TOKEN"),
            (
                "--agent",
                "opencode",
                "--model",
                "huggingface/deepseek-ai/DeepSeek-V4-Flash",
            ),
            (
                "--agent",
                "opencode",
                "--model",
                "opencode/big-pickle",
                "--opencode-auth-env",
                "HF_TOKEN",
            ),
            (
                "--agent",
                "opencode",
                "--model",
                "huggingface/deepseek-ai/DeepSeek-V4-Flash",
                "--opencode-auth-env",
                "OPENAI_API_KEY",
            ),
            (
                "--agent",
                "opencode",
                "--model",
                "huggingface/deepseek-ai/DeepSeek-V4-Flash",
                "--opencode-auth-file",
                str(valid),
                "--opencode-auth-env",
                "HF_TOKEN",
            ),
        )
        for arguments in semantic_cases:
            with self.subTest(arguments=arguments):
                completed = self.invoke(*arguments, "--dry-run")
                self.assertEqual(completed.returncode, 2)

        insecure = self.root / "insecure-auth.json"
        insecure.write_text(valid.read_text(encoding="utf-8"), encoding="utf-8")
        insecure.chmod(0o644)
        symlink = self.root / "linked-auth.json"
        symlink.symlink_to(valid)
        wrong_provider = self.root / "wrong-provider-auth.json"
        wrong_provider.write_text(
            json.dumps({"anthropic": {"type": "api", "key": "wrong-secret"}}),
            encoding="utf-8",
        )
        wrong_provider.chmod(0o600)
        oauth = self.root / "oauth-auth.json"
        oauth.write_text(
            json.dumps(
                {
                    "opencode": {
                        "type": "oauth",
                        "access": "oauth-secret",
                        "refresh": "refresh-secret",
                        "expires": 9999999999,
                    }
                }
            ),
            encoding="utf-8",
        )
        oauth.chmod(0o600)
        malformed = self.root / "malformed-auth.json"
        malformed.write_text('{"secret":"must-not-echo"', encoding="utf-8")
        malformed.chmod(0o600)
        oversized = self.root / "oversized-auth.json"
        oversized.write_bytes(b"x" * (eval_run.OPENCODE_AUTH_MAX_BYTES + 1))
        oversized.chmod(0o600)
        directory = self.root / "auth-directory"
        directory.mkdir()
        fifo = self.root / "auth-fifo"
        os.mkfifo(fifo, 0o600)

        invalid_sources = (
            insecure,
            symlink,
            wrong_provider,
            oauth,
            malformed,
            oversized,
            directory,
            fifo,
            self.root / "missing-auth.json",
        )
        for source in invalid_sources:
            with self.subTest(source=source.name):
                completed = self.invoke(
                    "--agent",
                    "opencode",
                    "--provider",
                    "opencode",
                    "--model",
                    "opencode/big-pickle",
                    "--opencode-auth-file",
                    str(source),
                    "--scenario",
                    "S01",
                )
                self.assertEqual(completed.returncode, 2)
                self.assertNotIn("must-not-echo", completed.stderr)
                self.assertNotIn("wrong-secret", completed.stderr)
                self.assertNotIn("oauth-secret", completed.stderr)

        for index, value in enumerate((None, "", " ", " padded-secret ")):
            with self.subTest(hf_token=value):
                invalid_env = self.env.copy()
                if value is None:
                    invalid_env.pop("HF_TOKEN", None)
                else:
                    invalid_env["HF_TOKEN"] = value
                output_dir = self.root / f"invalid-hf-token-{index}"
                completed = self.invoke(
                    "--agent",
                    "opencode",
                    "--provider",
                    "huggingface",
                    "--model",
                    "huggingface/deepseek-ai/DeepSeek-V4-Flash",
                    "--opencode-auth-env",
                    "HF_TOKEN",
                    "--scenario",
                    "S01",
                    "--output-dir",
                    str(output_dir),
                    env=invalid_env,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIn("missing, empty, or padded", completed.stderr)
                self.assertNotIn("padded-secret", completed.stderr)
                self.assertFalse(output_dir.exists())

    def test_dry_run_records_auth_intent_without_reading_source(self) -> None:
        missing = self.root / "not-read-during-dry-run.json"
        completed = self.invoke(
            "--agent",
            "opencode",
            "--provider",
            "opencode",
            "--model",
            "opencode/big-pickle",
            "--opencode-auth-file",
            str(missing),
            "--scenario",
            "S01",
            "--dry-run",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        plan = json.loads(completed.stdout)
        self.assertEqual(plan["credential_injection"], "isolated-auth-file")

        missing_env = self.env.copy()
        missing_env.pop("HF_TOKEN", None)
        completed = self.invoke(
            "--agent",
            "opencode",
            "--provider",
            "huggingface",
            "--model",
            "huggingface/deepseek-ai/DeepSeek-V4-Flash",
            "--opencode-auth-env",
            "HF_TOKEN",
            "--scenario",
            "S01",
            "--dry-run",
            env=missing_env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        plan = json.loads(completed.stdout)
        self.assertEqual(
            plan["credential_injection"], "isolated-auth-file-from-environment"
        )

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
