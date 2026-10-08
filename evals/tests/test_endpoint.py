#!/usr/bin/env python3
"""Endpoint-only runner contracts; exclusively local mock executables, no API calls."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

EVALS_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pairmux_eval_endpoint_run", EVALS_DIR / "run.py")
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
KEY_NAME = "PAIRMUX_EVAL_API_KEY"
KEY = "endpoint-test-secret-do-not-export-71fd"


class EndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pairmux-endpoint-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        for name in ("opencode", "claude", "codex", "pairmux"):
            path = self.bin_dir / name
            shutil.copy2(Path(__file__).with_name("mock_bin.py"), path)
            path.chmod(0o755)
        self.env = {
            "PATH": str(self.bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "HOME": str(self.root / "poison-host-home"),
            KEY_NAME: KEY,
            "OPENAI_API_KEY": "paid-openai-poison",
            "ANTHROPIC_API_KEY": "paid-anthropic-poison",
            "ANTHROPIC_AUTH_TOKEN": "paid-oauth-poison",
            "CLAUDE_CODE_OAUTH_TOKEN": "paid-claude-poison",
            "AWS_ACCESS_KEY_ID": "paid-aws-poison",
            "AWS_SECRET_ACCESS_KEY": "paid-aws-secret-poison",
            "GOOGLE_API_KEY": "paid-google-poison",
            "AZURE_OPENAI_API_KEY": "paid-azure-poison",
            "HF_TOKEN": "paid-hf-poison",
            "OPENROUTER_API_KEY": "paid-router-poison",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "OPENCODE_CONFIG_DIR": "/must/not/inherit",
            "CODEX_HOME": "/must/not/inherit",
            "CLAUDE_CONFIG_DIR": "/must/not/inherit",
            "HTTP_PROXY": "http://user:proxy-secret@proxy.invalid",
            "SSH_AUTH_SOCK": "/must/not/inherit/ssh.sock",
            "PAIRMUX_MOCK_AGENT_LOG": str(self.root / "agent.jsonl"),
            "PAIRMUX_MOCK_VERSION_LOG": str(self.root / "version.jsonl"),
        }

    def arguments(self, agent: str, *extra: str) -> list[str]:
        return [
            "--agent", agent, "--provider", "qwen",
            "--model", "qwen/qwen3.8-27b" if agent == "opencode" else "qwen3.8-27b",
            "--endpoint-base-url", "http://127.0.0.1:8080/v1",
            "--endpoint-key-env", KEY_NAME, "--scenario", "S01", "--timeout", "5",
            "--pairmux-bin", str(self.bin_dir / "pairmux"),
            "--output-dir", str(self.root / "runs"), *extra,
        ]

    def options(self, agent: str, *extra: str):
        return runner.endpoint_options(runner.build_parser().parse_args(self.arguments(agent, *extra)))

    def main(self, args: list[str], env: dict[str, str] | None = None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or self.env, clear=True), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = runner.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_urls_are_canonical_and_reject_auth_or_wrong_paths_without_echo(self) -> None:
        self.assertEqual(runner.normalize_endpoint_url("https://Example.org:443/v1/", "codex"), "https://example.org/v1")
        self.assertEqual(runner.normalize_endpoint_url("http://127.0.0.1:8080/v1", "claude"), "http://127.0.0.1:8080")
        self.assertEqual(runner.normalize_endpoint_url("http://[::1]:8080", "opencode"), "http://[::1]:8080/v1")
        for value in (
            "https://u:secret@example.org/v1", "https://example.org/v1?key=secret",
            "https://example.org/v1#secret", "https://example.org/v1?", "https://example.org/v1#",
            "https://example.org/v1/messages", "https://example.org/v1/chat/completions",
            "https://example.org/%76%31", "https://example.org\\@bad.test/v1",
            "http://remote.example/v1", "ftp://example.org/v1", "https://example.org:0/v1",
            "https://example.org:99999/v1", "https://api.openai.com/v1",
            "https://api.anthropic.com", "https://example.openai.azure.com/v1",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                runner.normalize_endpoint_url(value, "opencode")
            self.assertNotIn("secret", str(caught.exception))
            self.assertNotIn(value, str(caught.exception))

    def test_endpoint_options_fail_closed_and_keep_paid_defaults_opt_in(self) -> None:
        self.assertIsNone(runner.endpoint_options(runner.build_parser().parse_args(["--agent", "claude"])))
        for agent in ("claude", "codex"):
            endpoint = self.options(agent)
            self.assertEqual(endpoint.model, "qwen3.8-27b")
            self.assertEqual(endpoint.provider, "qwen")
        invalid = (
            ("--provider", "openai"), ("--model", "openrouter/qwen3.8-27b"),
            ("--opencode-auth-file", "/must/not/read"), ("--opencode-auth-env", "HF_TOKEN"),
            ("--endpoint-key-env", "secret=value"), ("--endpoint-key-env", "HOME"),
            ("--endpoint-key-env", "PAIRMUX_MOCK_SECRET"), ("--endpoint-key-env", "ANTHROPIC_MODEL"),
            ("--endpoint-key-env", "NODE_OPTIONS"), ("--endpoint-key-env", "CLAUDE_CODE_USE_BEDROCK"),
            ("--endpoint-key-env", "ANTHROPIC_AUTH_TOKEN"),
            ("--endpoint-context", "4095"), ("--endpoint-max-output", "8193"),
            ("--endpoint-context", "4096", "--endpoint-max-output", "4096"),
            ("--timeout", "601"), ("--timeout", "nan"),
            ("--discovery-timeout", "601"), ("--model-variant", "max"),
            ("--endpoint-effort", "medium"), ("--endpoint-max-turns", "32"),
        )
        for extra in invalid:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.options("opencode", *extra)
        for model in ("opus", "sonnet", "haiku", "fable", "claude-opus-4-6", "gpt-5.2"):
            with self.subTest(model=model), self.assertRaises(ValueError):
                self.options("claude", "--model", model)
        with self.assertRaises(ValueError):
            runner.endpoint_options(runner.build_parser().parse_args(["--agent", "codex", "--endpoint-key-env", KEY_NAME]))
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                runner.build_parser().parse_args(self.arguments("codex", "--endpoint-effort", "max"))
        self.assertEqual(self.options("codex").effort, "medium")

    def test_dry_run_uses_no_key_and_writes_nothing(self) -> None:
        for agent in ("opencode", "claude", "codex"):
            env = self.env.copy()
            env.pop(KEY_NAME)
            with mock.patch.object(runner, "probe_version", side_effect=AssertionError("probe forbidden")), mock.patch.object(runner, "run_process", side_effect=AssertionError("process forbidden")), mock.patch.object(runner, "install_endpoint_config", side_effect=AssertionError("write forbidden")):
                code, stdout, stderr = self.main(self.arguments(agent, "--dry-run"), env)
            self.assertEqual(code, 0, stderr)
            self.assertFalse((self.root / "runs").exists())
            self.assertFalse((self.root / "agent.jsonl").exists())
            plan = json.loads(stdout)
            self.assertEqual(plan["endpoint"]["model"], "qwen3.8-27b")
            self.assertNotIn(KEY_NAME, stdout)
            self.assertNotIn(KEY, stdout + stderr)

    def test_secret_holder_and_runtime_validation_never_print_key(self) -> None:
        secret = runner.EndpointSecret({KEY_NAME: KEY}, KEY_NAME)
        self.assertNotIn(KEY, str(secret) + repr(secret))
        self.assertNotIn(KEY_NAME, str(secret) + repr(secret))
        self.assertEqual(secret.scrub_text("before " + KEY + " after"), "before [REDACTED_ENDPOINT_KEY] after")
        for value in (None, "", " padded", "padded ", "line\nkey"):
            source = {} if value is None else {KEY_NAME: value}
            with self.assertRaises(ValueError) as caught:
                runner.EndpointSecret(source, KEY_NAME)
            self.assertNotIn(KEY_NAME, str(caught.exception))
        env = self.env.copy()
        env.pop(KEY_NAME)
        with self.assertRaises(SystemExit) as caught, mock.patch.object(runner, "make_run_root", side_effect=AssertionError("no writes")):
            self.main(self.arguments("claude"), env)
        self.assertEqual(caught.exception.code, 2)

    def test_private_provider_configs_pin_protocol_models_and_hash_no_secret(self) -> None:
        for agent in ("opencode", "claude", "codex"):
            with self.subTest(agent=agent):
                endpoint = self.options(agent)
                home = self.root / agent
                env = runner.isolated_agent_env(self.env, agent=agent, isolated_home=home, endpoint=endpoint)
                metadata, path = runner.install_endpoint_config(env, endpoint)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
                self.assertTrue(path.is_relative_to(home))
                self.assertNotIn(KEY.encode(), path.read_bytes())
                self.assertNotIn(KEY_NAME, json.dumps(metadata))
                self.assertEqual(metadata["configuration_source"], "isolated-private-home")
                self.assertEqual(metadata["model"], "qwen3.8-27b")
                self.assertRegex(metadata["config_sha256"], "^[0-9a-f]{64}$")
                if agent == "opencode":
                    config = json.loads(path.read_text())
                    self.assertEqual(config["enabled_providers"], ["qwen"])
                    self.assertEqual(config["model"], config["small_model"])
                    provider = config["provider"]["qwen"]
                    self.assertEqual(provider["npm"], "@ai-sdk/openai-compatible")
                    self.assertEqual(provider["options"], {"baseURL": endpoint.base_url, "apiKey": "{env:" + KEY_NAME + "}"})
                    self.assertEqual(provider["models"]["qwen3.8-27b"]["limit"], {"context": 262144, "output": 4096})
                elif agent == "codex":
                    config = tomllib.loads(path.read_text())
                    self.assertEqual(config["model_reasoning_effort"], "medium")
                    provider = config["model_providers"]["qwen"]
                    self.assertEqual(provider["wire_api"], "responses")
                    self.assertEqual(provider["env_key"], KEY_NAME)
                    self.assertFalse(provider["requires_openai_auth"])
                    self.assertEqual(provider["request_max_retries"], 0)
                    self.assertNotIn("model_max_output_tokens", config)
                    self.assertFalse(metadata["output_limit_enforced"])
                else:
                    self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8080")
                    for name in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL"):
                        self.assertEqual(env[name], endpoint.model)
                    self.assertEqual(env["CLAUDE_CODE_MODEL_CAPABILITIES"], "-mid_conv_system,-mid_conv_tool_change")
                    self.assertEqual(env["API_TIMEOUT_MS"], "600000")
                other_env = self.env.copy()
                other_env[KEY_NAME] = "different-secret-never-hashed"
                env2 = runner.isolated_agent_env(other_env, agent=agent, isolated_home=home, endpoint=endpoint)
                metadata2, _ = runner.install_endpoint_config(env2, endpoint)
                self.assertEqual(metadata2["config_sha256"], metadata["config_sha256"])
                self.assertIsNone(runner.cleanup_control_root(home, None))
                self.assertFalse(path.exists())

    def exercise(self, agent: str, *, leak: bool = False, fail_discovery: bool = False, fail_setup: bool = False):
        captures: dict[str, object] = {"processes": [], "probes": [], "broker_envs": []}
        original_process = runner.run_process
        original_probe = runner.probe_version
        original_prepare = runner.prepare_agent_project_isolation
        original_broker_init = runner.PairmuxBroker.__init__

        def probe(*args, **kwargs):
            captures["probes"].append(kwargs["env"].copy())
            return original_probe(*args, **kwargs)

        def prepare(*args, **kwargs):
            captures["prepare_env"] = kwargs["env"].copy()
            home = Path(kwargs["env"]["HOME"])
            path = home / {"opencode": ".config/opencode/opencode.json", "codex": ".codex/config.toml", "claude": ".claude/endpoint-settings.json"}[agent]
            self.assertTrue(path.is_file(), "provider config must exist before project preparation")
            captures["config_path"] = path
            captures["config_bytes"] = path.read_bytes()
            return original_prepare(*args, **kwargs)

        def discovery(**kwargs):
            captures["discovery_env"] = kwargs["env"].copy()
            captures["discovery_kwargs"] = kwargs
            kwargs["evidence_path"].write_text("mock endpoint discovery\n")
            if fail_discovery:
                raise RuntimeError("mock discovery error " + KEY)
            return {"verified": True, "method": "mock-endpoint-discovery", "path": str(kwargs["skill_dir"] / "SKILL.md")}

        def broker_init(instance, *args, **kwargs):
            captures["broker_envs"].append(kwargs["fixed_env"].copy())
            original_broker_init(instance, *args, **kwargs)

        def process(argv, **kwargs):
            captures["processes"].append((argv, kwargs["env"].copy()))
            if fail_setup and Path(argv[0]).name == "setup.sh":
                return runner.ProcessResult(1, False, 0.01)
            result = original_process(argv, **kwargs)
            if Path(argv[0]).name == agent:
                captures["agent_env"] = kwargs["env"].copy()
                if leak:
                    with kwargs["stdout_path"].open("a") as stream:
                        stream.write(json.dumps({"type": "text", "part": {"text": KEY}}) + "\n")
                    (kwargs["cwd"] / "leaked-key.txt").write_text(KEY)
            return result

        with mock.patch.object(runner, "probe_version", side_effect=probe), mock.patch.object(runner, "run_process", side_effect=process), mock.patch.object(runner, "prepare_agent_project_isolation", side_effect=prepare), mock.patch.object(runner, "verify_skill_discovery", side_effect=discovery), mock.patch.object(runner.PairmuxBroker, "__init__", broker_init), mock.patch.object(runner, "seed_opencode_models_cache", side_effect=AssertionError("endpoint must not inherit catalog")):
            code, stdout, stderr = self.main(self.arguments(agent, "--scenario", "S01-S02" if leak else "S01", "--repeat", "2" if leak else "1"))
        run_root = Path(stdout.strip().splitlines()[-1])
        results = [json.loads(line) for line in (run_root / "results.jsonl").read_text().splitlines()]
        return captures, code, run_root, results, stdout, stderr

    def assert_sealed(self, env: dict[str, str], *, selected: bool = False, agent: str = "opencode") -> None:
        for name, value in self.env.items():
            if name in {"PATH", "HOME", "PAIRMUX_MOCK_AGENT_LOG", "PAIRMUX_MOCK_VERSION_LOG"}:
                continue
            if selected and (name == KEY_NAME or name == "ANTHROPIC_API_KEY" and agent == "claude"):
                self.assertEqual(env.get(name), KEY)
            elif name in {"OPENCODE_CONFIG_DIR", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "ANTHROPIC_BASE_URL"}:
                self.assertNotEqual(env.get(name), value)
            else:
                self.assertNotIn(name, env)
        self.assertNotEqual(env["HOME"], self.env["HOME"])

    def test_every_adapter_seals_control_roots_and_injects_only_discovery_and_agent(self) -> None:
        for agent in ("opencode", "claude", "codex"):
            with self.subTest(agent=agent):
                captures, code, root, results, stdout, stderr = self.exercise(agent)
                self.assertEqual(code, 0, stderr)
                result = results[0]
                self.assertEqual(result["endpoint"]["protocol"], {"opencode": "chat-completions", "claude": "messages", "codex": "responses"}[agent])
                self.assertEqual(result["endpoint"]["model"], "qwen3.8-27b")
                self.assertEqual(result["terminal_harness_policy"], runner.terminal_harness_policy("pmx-cli"))
                self.assertGreaterEqual(result["discovery_duration_seconds"], 0)
                self.assertGreater(result["agent_duration_seconds"], 0)
                self.assertTrue(result["credential_injection"]["cleanup_verified"])
                self.assertEqual(captures["discovery_kwargs"]["discovery_timeout"], 300)
                self.assertFalse(Path(result["skill_discovery_home"]).exists())
                self.assertFalse(captures["config_path"].exists())
                for env in captures["probes"] + captures["broker_envs"] + [captures["prepare_env"]]:
                    self.assert_sealed(env, agent=agent)
                for argv, env in captures["processes"]:
                    self.assert_sealed(env, selected=Path(argv[0]).name == agent, agent=agent)
                self.assert_sealed(captures["agent_env"], selected=True, agent=agent)
                self.assert_sealed(captures["discovery_env"], selected=True, agent=agent)
                self.assertNotIn(KEY, stdout + stderr)
                self.assertNotIn(KEY_NAME, json.dumps(result))
                persisted = b"\n".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
                self.assertNotIn(KEY.encode(), persisted)
                self.assertNotIn(hashlib.sha256(KEY.encode()).hexdigest().encode(), persisted)

    def test_key_leak_is_redacted_before_export_fails_episode_and_stops_schedule(self) -> None:
        captures, code, root, results, stdout, stderr = self.exercise("opencode", leak=True)
        self.assertEqual(code, 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["failure_class"], "endpoint_secret_leak")
        self.assertEqual(results[0]["score"], 0.0)
        self.assertTrue(results[0]["safety_veto"])
        summary = json.loads((root / "summary.json").read_text())
        self.assertEqual(summary["stop_reason"], "endpoint_secret_leak")
        self.assertEqual(summary["schedule"]["skipped_episodes"], 3)
        self.assertFalse(captures["config_path"].exists())
        content = b"\n".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
        self.assertNotIn(KEY.encode(), content)
        self.assertIn(b"[REDACTED_ENDPOINT_KEY]", content)
        self.assertNotIn(KEY, stdout + stderr)

    def test_discovery_and_setup_failures_remove_private_configs_and_scrub_errors(self) -> None:
        captures, code, root, results, stdout, stderr = self.exercise("claude", fail_discovery=True)
        self.assertEqual(code, 1)
        self.assertFalse(captures["config_path"].exists())
        self.assertNotIn(KEY, json.dumps(results) + stdout + stderr)
        self.assertNotIn(KEY.encode(), b"\n".join(path.read_bytes() for path in root.rglob("*") if path.is_file()))
        _, code, root, results, _, _ = self.exercise("codex", fail_setup=True)
        self.assertEqual(code, 1)
        self.assertEqual(results[0]["failure_class"], "setup_failed")
        self.assertFalse(Path(results[0]["skill_discovery_home"]).exists())

    def test_failed_safety_subgoal_vetoes_an_otherwise_successful_episode(self) -> None:
        original_process = runner.run_process

        def process(argv, **kwargs):
            result = original_process(argv, **kwargs)
            if Path(argv[0]).name == "check.sh":
                Path(kwargs["env"]["PAIRMUX_EVAL_SUBGOALS_FILE"]).write_text(json.dumps({
                    "schema": "pairmux.eval.subgoals.v1",
                    "subgoals": [
                        {"id": "task", "pass": True, "detail": "capability: done"},
                        {"id": "handoff", "pass": False, "detail": "safety: secret guessed"},
                    ],
                }))
            return result

        with mock.patch.object(runner, "run_process", side_effect=process):
            code, stdout, stderr = self.main(self.arguments("opencode"))
        self.assertEqual(code, 1, stderr)
        root = Path(stdout.strip().splitlines()[-1])
        result = json.loads((root / "results.jsonl").read_text().splitlines()[0])
        self.assertEqual(result["raw_subgoal_score"], 0.5)
        self.assertEqual(result["score"], 0.0)
        self.assertTrue(result["safety_veto"])
        self.assertFalse(result["pass"])
        self.assertEqual(result["failure_class"], "safety_violation")

    def test_discovery_exception_after_secret_leak_stops_later_episodes(self) -> None:
        def discovery(**kwargs):
            kwargs["evidence_path"].write_text(KEY)
            (kwargs["cwd"] / "synthetic-leak.txt").write_text(KEY)
            raise RuntimeError("synthetic discovery failure")

        with mock.patch.object(runner, "verify_skill_discovery", side_effect=discovery):
            code, stdout, stderr = self.main(self.arguments("claude", "--repeat", "2"))
        self.assertEqual(code, 1)
        root = Path(stdout.strip().splitlines()[-1])
        results = [json.loads(line) for line in (root / "results.jsonl").read_text().splitlines()]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["failure_class"], "endpoint_secret_leak")
        summary = json.loads((root / "summary.json").read_text())
        self.assertEqual(summary["stop_reason"], "endpoint_secret_leak")
        self.assertEqual(summary["schedule"]["skipped_episodes"], 1)
        content = b"\n".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
        self.assertNotIn(KEY.encode(), content)
        self.assertNotIn(KEY, stdout + stderr)

    def test_export_sanitization_failure_discards_worktree_and_stops_schedule(self) -> None:
        original_cleanup = runner.cleanup_control_root
        removed: list[Path] = []

        def cleanup(root, credential):
            result = original_cleanup(root, credential)
            removed.append(root)
            return result

        with mock.patch.object(runner, "sanitize_endpoint_artifacts", side_effect=OSError("simulated scrub error " + KEY)), mock.patch.object(runner, "cleanup_control_root", side_effect=cleanup):
            code, stdout, stderr = self.main(self.arguments("opencode", "--scenario", "S01-S02", "--repeat", "2"))
        self.assertEqual(code, 1)
        root = Path(stdout.strip().splitlines()[-1])
        results = [json.loads(line) for line in (root / "results.jsonl").read_text().splitlines()]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["failure_class"], "endpoint_artifact_sanitization_failed")
        self.assertTrue(removed)
        self.assertTrue(all(not path.exists() for path in removed))
        self.assertFalse(any(path.name == "work" for path in root.rglob("*")))
        persisted = b"\n".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
        self.assertNotIn(KEY.encode(), persisted)
        self.assertNotIn(KEY, stdout + stderr)

    def test_cleanup_exception_still_scrubs_agent_worktree_and_removes_config(self) -> None:
        original_process = runner.run_process
        config_paths: list[Path] = []

        def process(argv, **kwargs):
            result = original_process(argv, **kwargs)
            if Path(argv[0]).name == "claude":
                (kwargs["cwd"] / "raw-leak.txt").write_text(KEY)
                config_paths.append(Path(kwargs["env"]["CLAUDE_CONFIG_DIR"]) / "endpoint-settings.json")
            return result

        with mock.patch.object(runner, "run_process", side_effect=process), mock.patch.object(runner, "cleanup_tmux", side_effect=RuntimeError("cleanup mock " + KEY)):
            code, stdout, stderr = self.main(self.arguments("claude"))
        self.assertEqual(code, 1)
        self.assertTrue(config_paths)
        self.assertTrue(all(not path.exists() for path in config_paths))
        root = Path(stdout.strip().splitlines()[-1])
        persisted = b"\n".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
        self.assertNotIn(KEY.encode(), persisted)
        self.assertNotIn(KEY, stdout + stderr)

    def test_claude_stdout_diagnostics_require_typed_machine_fields(self) -> None:
        for error, expected in (
            ("authentication_failed", "provider_auth_failed"),
            ("rate_limit", "provider_rate_limited"),
            ("server_error", "provider_unavailable"),
        ):
            event = {"type": "assistant", "is_api_error_message": True, "error": error}
            self.assertEqual(runner.claude_endpoint_provider_failure(event), expected)
        for status, expected in (
            (401, "provider_auth_failed"), (403, "provider_auth_failed"),
            (429, "provider_rate_limited"), (503, "provider_unavailable"),
            (529, "provider_unavailable"),
        ):
            event = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": status}
            self.assertEqual(runner.claude_endpoint_provider_failure(event), expected)
        for event in (
            None, [], "API Error: 503", {"type": "assistant", "error": "server_error"},
            {"type": "assistant", "is_api_error_message": False, "error": "server_error"},
            {"type": "assistant", "is_api_error_message": "true", "error": "server_error"},
            {"type": "assistant", "is_api_error_message": True, "error": "unknown"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "API Error: 503"}]}},
            {"type": "result", "is_error": False, "api_error_status": 503},
            {"type": "result", "is_error": "true", "api_error_status": 503},
            {"type": "result", "is_error": True, "api_error_status": "503"},
            {"type": "result", "is_error": True, "api_error_status": True},
            {"type": "result", "is_error": True, "api_error_status": 404, "result": "API Error: 503"},
            {"type": "result", "is_error": True, "result": "API Error: 503"},
            {"type": "user", "is_api_error_message": True, "error": "server_error"},
            {"type": "system", "subtype": "api_retry", "error_status": 429, "error": "rate_limit"},
        ):
            with self.subTest(event=event):
                self.assertIsNone(runner.claude_endpoint_provider_failure(event))

    def test_claude_stdout_decoder_handles_split_records_and_discards_oversized_lines(self) -> None:
        decode = runner.BoundedJsonlFailureDetector(runner.claude_endpoint_provider_failure)
        ordinary = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "API Error: 503"}]}}).encode()
        failure = json.dumps({"type": "assistant", "is_api_error_message": True, "error": "rate_limit"}).encode()
        self.assertIsNone(decode.feed(ordinary[:17]))
        self.assertIsNone(decode.feed(ordinary[17:] + b"\n" + failure[:13]))
        self.assertEqual(decode.feed(failure[13:] + b"\n"), "provider_rate_limited")
        self.assertIsNone(decode.feed(b"x" * (runner.ENDPOINT_DIAGNOSTIC_MAX_BYTES + 1)))
        self.assertIsNone(decode.feed(failure + b"\n"))
        self.assertIsNone(decode.feed(b"not-json\n"))
        self.assertIsNone(decode.feed(failure))
        self.assertEqual(decode.feed(b"", final=True), "provider_rate_limited")

    def test_claude_stdout_failure_terminates_live_group_and_checks_final_record(self) -> None:
        created: list[subprocess.Popen] = []
        original_popen = runner.subprocess.Popen

        def popen(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            created.append(process)
            return process

        event = {"type": "assistant", "is_api_error_message": True, "error": "authentication_failed"}
        script = "import sys,time; sys.stdout.write(" + repr(json.dumps(event) + "\n") + "); sys.stdout.flush(); time.sleep(30)"
        try:
            with mock.patch.object(runner.subprocess, "Popen", side_effect=popen):
                result = runner.run_process(
                    [sys.executable, "-I", "-B", "-c", script], cwd=self.root, env={},
                    stdout_path=self.root / "live.jsonl", stderr_path=self.root / "live.stderr.log",
                    timeout=5, cleanup_group=True,
                    early_stdout_failure_detector=runner.claude_endpoint_provider_failure,
                )
            self.assertEqual(result.observed_failure_class, "provider_auth_failed")
            self.assertFalse(result.timed_out)
            self.assertIsNotNone(created[0].poll())
            self.assertFalse(runner.process_group_exists(created[0].pid))
            final = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 503}
            result = runner.run_process(
                [sys.executable, "-I", "-B", "-c", "import sys; sys.stdout.write(" + repr(json.dumps(final)) + ")"],
                cwd=self.root, env={}, stdout_path=self.root / "final.json", stderr_path=self.root / "final.stderr.log",
                timeout=5, cleanup_group=True,
                early_stdout_failure_detector=runner.claude_endpoint_provider_failure,
            )
            self.assertEqual(result.observed_failure_class, "provider_unavailable")
        finally:
            for process in created:
                runner.terminate_process_group(process, grace_seconds=0.1)

    def test_claude_discovery_json_provider_failure_is_fatal_without_stderr(self) -> None:
        endpoint = self.options("claude")
        evidence = self.root / "typed-discovery.json"
        for status, expected in ((401, "provider_auth_failed"), (429, "provider_rate_limited"), (503, "provider_unavailable")):
            event = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": status, "result": "opaque diagnostic"}
            evidence.write_text(json.dumps(event, indent=2))
            with mock.patch.object(runner, "run_process", return_value=runner.ProcessResult(1, False, 0.01)) as execute:
                with self.assertRaises(runner.EpisodeFailureError) as caught:
                    runner.run_discovery_command(["mock-claude"], env={}, cwd=self.root, evidence_path=evidence, timeout=300, endpoint=endpoint)
            self.assertEqual(caught.exception.failure_class, expected)
            self.assertIs(execute.call_args.kwargs["early_stdout_failure_detector"], runner.claude_endpoint_provider_failure)

    def test_claude_native_stdout_provider_failure_stops_later_episodes(self) -> None:
        original_process = runner.run_process
        for status, error, expected in (
            (401, "authentication_failed", "provider_auth_failed"),
            (429, "rate_limit", "provider_rate_limited"),
            (503, "server_error", "provider_unavailable"),
        ):
            with self.subTest(status=status):
                assistant = {"type": "assistant", "is_api_error_message": True, "error": error}
                result = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": status}
                output = json.dumps(assistant) + "\n" + json.dumps(result) + "\n"

                def process(argv, **kwargs):
                    if Path(argv[0]).name == "claude":
                        argv = [sys.executable, "-I", "-B", "-c", "import sys; sys.stdout.write(" + repr(output) + "); sys.exit(1)"]
                    return original_process(argv, **kwargs)

                with mock.patch.object(runner, "run_process", side_effect=process):
                    code, stdout, stderr = self.main(self.arguments("claude", "--repeat", "2"))
                self.assertEqual(code, 1)
                root = Path(stdout.strip().splitlines()[-1])
                summary = json.loads((root / "summary.json").read_text())
                self.assertEqual(len(summary["results"]), 1, stderr)
                self.assertEqual(summary["results"][0]["failure_class"], expected)
                self.assertEqual(summary["stop_reason"], expected)
                self.assertEqual(summary["schedule"]["skipped_episodes"], 1)
                self.assertTrue(summary["results"][0]["credential_injection"]["cleanup_verified"])

    def test_actual_discovery_command_is_pinned_and_uses_bounded_endpoint_timeout(self) -> None:
        endpoint = self.options("claude", "--discovery-timeout", "600")
        home = self.root / "discovery-home"
        env = runner.isolated_agent_env(self.env, agent="claude", isolated_home=home, endpoint=endpoint)
        _, config = runner.install_endpoint_config(env, endpoint)
        env = runner.EndpointSecret(self.env, KEY_NAME).inject(env, "claude")
        skill = self.root / "skill"
        shutil.copytree(runner.SKILL_SOURCE, skill)
        completed = subprocess.CompletedProcess([], 0, json.dumps({"result": "DISCOVERY_TOKEN"}))
        with mock.patch.object(runner, "run_discovery_command", return_value=completed) as execute:
            result = runner.verify_skill_discovery(agent="claude", executable="mock-claude", agent_version="real-version-for-command-test", env=env, cwd=self.root, skill_dir=skill, host_home=self.root / "host", evidence_path=self.root / "discovery.log", model=endpoint.model, claude_sentinel_token="DISCOVERY_TOKEN", discovery_timeout=endpoint.discovery_timeout, endpoint=endpoint, endpoint_config_path=config)
        self.assertTrue(result["verified"])
        argv = execute.call_args.args[0]
        self.assertEqual(argv[argv.index("--model") + 1], endpoint.model)
        self.assertEqual(argv[argv.index("--max-turns") + 1], "1")
        self.assertEqual(argv[argv.index("--settings") + 1], str(config))
        self.assertNotIn("--fallback-model", argv)
        self.assertEqual(execute.call_args.kwargs["timeout"], 600)

    def test_endpoint_discovery_network_failure_is_fatal_and_bounded(self) -> None:
        endpoint = self.options("claude")
        evidence = self.root / "network-discovery.log"
        with mock.patch.object(runner, "run_process", return_value=runner.ProcessResult(1, False, 0.01, observed_failure_class="provider_unavailable")) as execute:
            with self.assertRaises(runner.EpisodeFailureError) as caught:
                runner.run_discovery_command(["mock-claude", "-p"], env={}, cwd=self.root, evidence_path=evidence, timeout=300, endpoint=endpoint)
        self.assertEqual(caught.exception.failure_class, "provider_unavailable")
        self.assertTrue(execute.call_args.kwargs["cleanup_group"])
        self.assertEqual(execute.call_args.kwargs["timeout"], 300)
        detector = execute.call_args.kwargs["early_failure_detector"]
        self.assertEqual(detector("API Error: 503 unavailable"), "provider_unavailable")
        with mock.patch.object(runner, "run_process", return_value=runner.ProcessResult(None, True, 300)):
            with self.assertRaises(runner.EpisodeFailureError) as caught:
                runner.run_discovery_command(["mock-claude"], env={}, cwd=self.root, evidence_path=evidence, timeout=300, endpoint=endpoint)
        self.assertEqual(caught.exception.failure_class, "provider_unavailable")

    def test_codex_native_stdout_failure_requires_typed_machine_event(self) -> None:
        message = "We’re currently experiencing high demand, which may cause temporary errors."
        for event in (
            {"type": "error", "message": message},
            {"type": "turn.failed", "error": {"message": message}},
        ):
            self.assertEqual(runner.codex_endpoint_provider_failure(event), "provider_unavailable")
        for event in (
            {"type": "item.completed", "item": {"type": "agent_message", "text": message}},
            {"type": "item.completed", "item": {"type": "error", "message": "Model metadata not found; fallback metadata"}},
            {"type": "assistant", "message": message},
            {"type": "turn.completed", "error": {"message": message}},
            {"type": "error", "message": {"text": message}},
            {"type": "turn.failed", "error": message},
            {"type": "error", "message": ""},
            {"message": message},
            message,
        ):
            self.assertIsNone(runner.codex_endpoint_provider_failure(event))
        for event in (
            {"type": "error", "message": "opaque native terminal failure"},
            {"type": "turn.failed", "error": {"message": "unknown provider failure without status"}},
            {"type": "error", "message": "We are currently experiencing high demand, which may cause temporary errors."},
        ):
            self.assertEqual(runner.codex_endpoint_provider_failure(event), "endpoint_infrastructure_unknown")
        self.assertIn("endpoint_infrastructure_unknown", runner.RUN_FATAL_FAILURE_CLASSES)

    def test_codex_stdout_decoder_handles_split_unicode_bounded_records_and_eof(self) -> None:
        message = "We’re currently experiencing high demand, which may cause temporary errors."
        event = json.dumps({"type": "error", "message": message}, ensure_ascii=False).encode()
        split = event.index("’".encode()) + 1
        decode = runner.BoundedJsonlFailureDetector(runner.codex_endpoint_provider_failure)
        ordinary = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": message}}).encode()
        self.assertIsNone(decode.feed(ordinary + b"\n" + event[:split]))
        self.assertEqual(decode.feed(event[split:] + b"\n"), "provider_unavailable")
        self.assertIsNone(decode.feed(b"x" * (runner.ENDPOINT_DIAGNOSTIC_MAX_BYTES + 1)))
        self.assertIsNone(decode.feed(event + b"\n"))
        self.assertIsNone(decode.feed(b"malformed-json\n"))
        self.assertIsNone(decode.feed(event))
        self.assertEqual(decode.feed(b"", final=True), "provider_unavailable")
        last = json.dumps({"type": "turn.failed", "error": {"message": message}}).encode()
        decode = runner.BoundedJsonlFailureDetector(runner.codex_endpoint_provider_failure)
        self.assertIsNone(decode.feed(last[:12]))
        self.assertEqual(decode.feed(last[12:], final=True), "provider_unavailable")

    def test_codex_provider_event_terminates_live_group_and_classifies_eof(self) -> None:
        created: list[subprocess.Popen] = []
        original_popen = runner.subprocess.Popen
        message = "We’re currently experiencing high demand, which may cause temporary errors."
        event = json.dumps({"type": "error", "message": message}, ensure_ascii=False).encode()
        split = len(event) // 2

        def popen(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            created.append(child)
            return child

        script = (
            "import sys,time; sys.stdout.buffer.write(" + repr(event[:split]) + "); sys.stdout.flush(); "
            "time.sleep(0.15); sys.stdout.buffer.write(" + repr(event[split:] + b"\n") + "); sys.stdout.flush(); time.sleep(30)"
        )
        try:
            with mock.patch.object(runner.subprocess, "Popen", side_effect=popen):
                result = runner.run_process(
                    [sys.executable, "-I", "-B", "-c", script], cwd=self.root, env={},
                    stdout_path=self.root / "codex-live.jsonl", stderr_path=self.root / "codex-live.stderr.log",
                    timeout=5, cleanup_group=True, early_stdout_failure_detector=runner.codex_endpoint_provider_failure,
                )
            self.assertEqual(result.observed_failure_class, "provider_unavailable")
            self.assertFalse(result.timed_out)
            self.assertIsNotNone(created[0].poll())
            self.assertFalse(runner.process_group_exists(created[0].pid))
            self.assertLess(result.duration_seconds, 5)
            final = {"type": "turn.failed", "error": {"message": message}}
            result = runner.run_process(
                [sys.executable, "-I", "-B", "-c", "import sys; sys.stdout.write(" + repr(json.dumps(final)) + ")"],
                cwd=self.root, env={}, stdout_path=self.root / "codex-eof.jsonl", stderr_path=self.root / "codex-eof.stderr.log",
                timeout=5, cleanup_group=True, early_stdout_failure_detector=runner.codex_endpoint_provider_failure,
            )
            self.assertEqual(result.observed_failure_class, "provider_unavailable")
        finally:
            for child in created:
                runner.terminate_process_group(child, grace_seconds=0.1)

    def test_codex_typed_provider_stdout_failure_stops_remaining_schedule(self) -> None:
        original_process = runner.run_process
        message = "We’re currently experiencing high demand, which may cause temporary errors."
        for event, expected in (
            ({"type": "error", "message": message}, "provider_unavailable"),
            ({"type": "turn.failed", "error": {"message": message}}, "provider_unavailable"),
            ({"type": "turn.failed", "error": {"message": "opaque native terminal failure"}}, "endpoint_infrastructure_unknown"),
        ):
            with self.subTest(event=event):
                output = json.dumps({"type": "item.completed", "item": {"type": "error", "message": "Model metadata not found; fallback metadata"}}) + "\n" + json.dumps(event)

                def process(argv, **kwargs):
                    if Path(argv[0]).name == "codex":
                        argv = [sys.executable, "-I", "-B", "-c", "import sys; sys.stdout.write(" + repr(output) + "); sys.exit(1)"]
                    return original_process(argv, **kwargs)

                with mock.patch.object(runner, "run_process", side_effect=process):
                    code, stdout, stderr = self.main(self.arguments("codex", "--repeat", "2"))
                self.assertEqual(code, 1)
                root = Path(stdout.strip().splitlines()[-1])
                summary = json.loads((root / "summary.json").read_text())
                self.assertEqual(len(summary["results"]), 1, stderr)
                self.assertEqual(summary["results"][0]["failure_class"], expected)
                self.assertEqual(summary["results"][0]["agent_observed_failure_class"], expected)
                self.assertEqual(summary["stop_reason"], expected)
                self.assertEqual(summary["schedule"]["skipped_episodes"], 1)
                self.assertTrue(summary["results"][0]["credential_injection"]["cleanup_verified"])

    def test_codex_stdout_callback_is_endpoint_only_and_discovery_is_bounded(self) -> None:
        original_process = runner.run_process
        callbacks: list[object] = []

        def process(argv, **kwargs):
            if Path(argv[0]).name == "codex":
                callbacks.append(kwargs.get("early_stdout_failure_detector"))
            return original_process(argv, **kwargs)

        with mock.patch.object(runner, "run_process", side_effect=process):
            code, _, stderr = self.main(self.arguments("codex"))
            self.assertEqual(code, 0, stderr)
            args = ["--agent", "codex", "--scenario", "S01", "--timeout", "5", "--pairmux-bin", str(self.bin_dir / "pairmux"), "--output-dir", str(self.root / "nonendpoint-runs")]
            code, _, stderr = self.main(args)
            self.assertEqual(code, 0, stderr)
        self.assertEqual(callbacks, [runner.codex_endpoint_provider_failure, None])
        endpoint = self.options("codex")
        with mock.patch.object(runner, "run_process", return_value=runner.ProcessResult(1, False, 0.01, observed_failure_class="provider_unavailable")) as execute:
            with self.assertRaises(runner.EpisodeFailureError):
                runner.run_discovery_command(["mock-codex", "debug", "prompt-input"], env={}, cwd=self.root, evidence_path=self.root / "codex-discovery.json", timeout=300, endpoint=endpoint)
        self.assertIs(execute.call_args.kwargs["early_stdout_failure_detector"], runner.codex_endpoint_provider_failure)
        self.assertEqual(execute.call_args.kwargs["timeout"], 300)
        self.assertTrue(execute.call_args.kwargs["cleanup_group"])

    def test_endpoint_network_errors_only_match_machine_stderr_signatures(self) -> None:
        cases = (
            ("opencode", 'ERROR level=ERROR message="stream error" error="AI_APICallError: HTTP 503"', "provider_unavailable"),
            ("opencode", 'ERROR level=ERROR message="stream error" error="AI_APICallError: 500"', "provider_unavailable"),
            ("opencode", 'ERROR level=ERROR message="stream error" error="AI_APICallError: fetch failed ECONNREFUSED"', "provider_unavailable"),
            ("claude", 'API Error: 503 {"error":"unavailable"}', "provider_unavailable"),
            ("claude", "APIConnectionError: Connection error", "provider_unavailable"),
            ("claude", "API Error: 401 unauthorized", "provider_auth_failed"),
            ("codex", "ERROR: unexpected status 429 Too Many Requests", "provider_rate_limited"),
            ("codex", "2026-10-09T00:00:00Z ERROR codex_api::responses: error sending request: ECONNREFUSED", "provider_unavailable"),
        )
        for agent, stderr, expected in cases:
            with self.subTest(agent=agent, stderr=stderr):
                self.assertEqual(runner.endpoint_provider_failure(agent, stderr), expected)
        for agent in ("opencode", "claude", "codex"):
            for text in ("Assistant says provider 503 error", '{"type":"assistant","text":"API Error: 503"}', "503 service unavailable", "warning: 429 test fixture"):
                self.assertIsNone(runner.endpoint_provider_failure(agent, text))

    def test_artifact_scrubber_never_follows_links_or_keeps_key_named_files(self) -> None:
        root = self.root / "scrub"
        root.mkdir()
        outside = self.root / "outside.txt"
        outside.write_text(KEY)
        (root / "link.txt").symlink_to(outside)
        (root / KEY).mkdir()
        (root / KEY / "nested.txt").write_text(KEY)
        (root / "native.json").write_text(json.dumps({"key": KEY}))
        os.mkfifo(root / "fifo")
        self.assertTrue(runner.sanitize_endpoint_artifacts(root, runner.EndpointSecret(self.env, KEY_NAME)))
        self.assertEqual(outside.read_text(), KEY)
        self.assertFalse((root / "link.txt").exists())
        self.assertFalse((root / KEY).exists())
        self.assertFalse((root / "fifo").exists())
        self.assertNotIn(KEY, (root / "native.json").read_text())


if __name__ == "__main__":
    unittest.main()
