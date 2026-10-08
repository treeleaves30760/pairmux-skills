#!/usr/bin/env python3
"""Model-free Codex compressed discovery/version contracts (no real CLI/API)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

EVALS_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pairmux_eval_codex_discovery_run", EVALS_DIR / "run.py")
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class CodexDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="pairmux-codex-discovery-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "private-home"
        self.skill = self.home / ".agents/skills/pairmux"
        shutil.copytree(runner.SKILL_SOURCE, self.skill)
        self.expected = (self.skill / "SKILL.md").resolve()

    def payload(self, text: str, *, role: str = "developer", kind: str = "host_skills.instructions") -> str:
        return json.dumps([
            {
                "type": "message", "role": role,
                "content": [{"type": "input_text", "text": text}],
                "internal_chat_message_metadata_passthrough": {"content_item_kinds": [kind]},
            },
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "pairmux-eval-discovery"}]},
        ])

    def instructions(self, reference: str = "r0/pairmux/SKILL.md", *, roots: str | None = None) -> str:
        if roots is None:
            # The system root need not exist: Codex may create it itself later.
            roots = (
                f"### Skill roots\n- `r0` = `{self.home}/.agents/skills`\n"
                f"- `r1` = `{self.home}/.codex/skills/.system`\n"
            )
        return (
            "<skills_instructions>\n## Skills\n" + roots + "### Available skills\n"
            "- system-test: Built-in system skill. (file: r1/system-test/SKILL.md)\n"
            f"- pairmux: Canonical test skill. (file: {reference})\n</skills_instructions>"
        )

    def verify(self, output: str):
        completed = subprocess.CompletedProcess([], 0, output)
        with mock.patch.object(runner, "run_discovery_command", return_value=completed) as execute:
            result = runner.verify_skill_discovery(
                agent="codex", executable="never-run-codex", agent_version="codex-cli 0.160.1",
                env={"HOME": str(self.home)}, cwd=self.root, skill_dir=self.skill,
                host_home=self.root / "host", evidence_path=self.root / "discovery.log",
            )
        self.assertEqual(execute.call_args.args[0], ["never-run-codex", "debug", "prompt-input", "pairmux-eval-discovery"])
        return result

    def test_compressed_roots_resolve_registered_pairmux_to_exact_private_skill(self) -> None:
        output = self.payload(self.instructions())
        self.assertNotIn(str(self.expected), output)
        result = self.verify(output)
        self.assertTrue(result["verified"])
        self.assertEqual(result["path"], str(self.expected))
        self.assertEqual(result["method"], "codex-debug-prompt-input")
        self.assertFalse((self.home / ".codex/skills/.system").exists())

    def test_legacy_absolute_registered_skill_remains_supported(self) -> None:
        text = f"<skills_instructions>\n## Skills\n### Available skills\n- pairmux: Legacy absolute path. (file: {self.expected})\n</skills_instructions>"
        result = self.verify(self.payload(text))
        self.assertTrue(result["verified"])
        self.assertEqual(result["path"], str(self.expected))

    def test_user_text_other_developer_metadata_and_substrings_cannot_prove_discovery(self) -> None:
        for output in (
            self.payload(self.instructions(), role="user"),
            self.payload(self.instructions(), kind="permissions.instructions"),
            self.payload(f"The skill path is {self.expected}, but it was not registered."),
            self.payload(self.instructions().replace("- pairmux:", "- not-pairmux:")),
            self.payload(self.instructions("r0/pairmux/SKILL.md.bak")),
            self.payload(self.instructions("r0/pairmux/SKILL.md/extra")),
            self.payload(self.instructions().replace("</skills_instructions>", "- pairmux: Duplicate registration. (file: r0/pairmux/SKILL.md)\n</skills_instructions>")),
        ):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                self.verify(output)

    def test_duplicate_unknown_or_malformed_root_and_traversal_fail_closed(self) -> None:
        base = f"### Skill roots\n- `r0` = `{self.home}/.agents/skills`\n- `r1` = `{self.home}/.codex/skills/.system`\n"
        for text in (
            self.instructions("r9/pairmux/SKILL.md"),
            self.instructions("r0/../skills/pairmux/SKILL.md"),
            self.instructions("r0//pairmux/SKILL.md"),
            self.instructions("r0/./pairmux/SKILL.md"),
            self.instructions(roots=base + f"- `r0` = `{self.home}/other`\n"),
            self.instructions(roots=base.replace(f"`{self.home}/.agents/skills`", "`relative/skills`")),
            self.instructions(roots=base.replace("- `r0` =", "- r0 =")),
            self.instructions(roots=base.replace(f"`{self.home}/.agents/skills`", f"`{self.root}/host/skills`")),
        ):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                self.verify(self.payload(text))

    def test_compressed_host_skill_leak_and_symlink_escape_fail_closed(self) -> None:
        outside = self.root / "host/skills"
        outside.mkdir(parents=True)
        escaped = self.home / "escape"
        escaped.symlink_to(outside, target_is_directory=True)
        for roots in (
            f"### Skill roots\n- `r0` = `{self.home}/.agents/skills`\n- `r1` = `{outside}`\n",
            f"### Skill roots\n- `r0` = `{self.home}/.agents/skills`\n- `r1` = `{escaped}`\n",
        ):
            with self.subTest(roots=roots), self.assertRaises(RuntimeError):
                self.verify(self.payload(self.instructions(roots=roots)))

    def test_version_private_roots_exist_before_cli_probe_and_warning_is_not_version(self) -> None:
        parser_args = runner.build_parser().parse_args([
            "--agent", "codex", "--provider", "qwen", "--model", "qwen3.8-27b",
            "--endpoint-base-url", "http://127.0.0.1:8080/v1", "--endpoint-key-env", "PAIRMUX_EVAL_API_KEY",
        ])
        endpoint = runner.endpoint_options(parser_args)
        probe_home = self.root / "probe-home"
        env = runner.isolated_version_probe_env({"PATH": "/mock/path", "PAIRMUX_EVAL_API_KEY": "never-pass", "OPENAI_API_KEY": "never-pass"}, probe_home, endpoint=endpoint)
        for name in ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "OPENCODE_CONFIG_DIR", "CODEX_HOME", "CLAUDE_CONFIG_DIR"):
            self.assertTrue(Path(env[name]).is_dir(), name)
            self.assertTrue(Path(env[name]).is_relative_to(probe_home))
        self.assertNotIn("PAIRMUX_EVAL_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        process = mock.Mock(returncode=0)
        process.communicate.return_value = (b"WARNING: CODEX_HOME is ignored\ncodex-cli 0.160.1\n", None)
        with mock.patch.object(runner.subprocess, "Popen", return_value=process):
            version = runner.probe_version("/fake/bin/codex", env=env, cwd=probe_home)
        self.assertEqual(version, "codex-cli 0.160.1")

    def test_mock_version_and_discovery_contract_remain_supported(self) -> None:
        process = mock.Mock(returncode=0)
        process.communicate.return_value = (b"codex mock-1.0\n", None)
        with mock.patch.object(runner.subprocess, "Popen", return_value=process):
            self.assertEqual(runner.probe_version("/fake/codex", env={}, cwd=self.root), "codex mock-1.0")
        with mock.patch.object(runner, "run_discovery_command", side_effect=AssertionError("mock does not run CLI")):
            result = runner.verify_skill_discovery(agent="codex", executable="mock-codex", agent_version="codex mock-1.0", env={"HOME": str(self.home)}, cwd=self.root, skill_dir=self.skill, host_home=self.root / "host", evidence_path=self.root / "mock-discovery.log")
        self.assertTrue(result["verified"])
        self.assertEqual(result["method"], "model-free-mock-contract")


if __name__ == "__main__":
    unittest.main()
