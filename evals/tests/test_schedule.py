#!/usr/bin/env python3
"""Model-free bounded scheduling contracts; episodes are entirely synthetic."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

EVALS_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pairmux_eval_schedule_run", EVALS_DIR / "run.py")
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pairmux-schedule-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        for name in ("codex", "pairmux"):
            target = self.bin_dir / name
            shutil.copy2(Path(__file__).with_name("mock_bin.py"), target)
            target.chmod(0o755)
        self.env = {"PATH": str(self.bin_dir) + os.pathsep + os.environ.get("PATH", "")}

    def invoke(self, failures: list[str | None], *extra: str, safety: bool = False):
        calls = []

        def episode(**kwargs):
            index = len(calls)
            calls.append(kwargs["scenario"])
            failure = failures[index] if index < len(failures) else None
            return {
                "schema": runner.RESULT_SCHEMA,
                "run_id": kwargs["run_id"],
                "episode_id": f"{kwargs['scenario']}-synthetic",
                "scenario": kwargs["scenario"],
                "repeat": kwargs["repetition"],
                "pass": failure is None and not safety,
                "score": 1.0 if failure is None and not safety else 0.0,
                "outcome": "passed" if failure is None and not safety else "failed",
                "steps": 0,
                "broker_policy_rejections": 0,
                "wall_time_seconds": 0.01,
                "failure_class": failure,
                "safety_veto": safety,
            }

        stdout, stderr = io.StringIO(), io.StringIO()
        arguments = [
            "--agent", "codex", "--model", "mock-model", "--provider", "mock",
            "--scenario", "S01-S06", "--pairmux-bin", str(self.bin_dir / "pairmux"),
            "--output-dir", str(self.root / "runs"), *extra,
        ]
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(runner, "probe_version", return_value="mock-1.0"), mock.patch.object(runner, "run_episode", side_effect=episode), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = runner.main(arguments)
        run_root = Path(stdout.getvalue().strip().splitlines()[-1])
        summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(len((run_root / "results.jsonl").read_text(encoding="utf-8").splitlines()), len(calls))
        return code, calls, summary, stderr.getvalue()

    def test_limit_must_be_positive_and_is_opt_in(self) -> None:
        parser = runner.build_parser()
        self.assertIsNone(parser.parse_args(["--agent", "codex"]).max_capability_failures)
        self.assertEqual(parser.parse_args(["--agent", "codex", "--max-capability-failures", "2"]).max_capability_failures, 2)
        for value in ("0", "-1", "nan"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(["--agent", "codex", "--max-capability-failures", value])
        self.assertFalse((self.root / "runs").exists())

    def test_historical_default_continues_capability_and_runner_failures(self) -> None:
        code, calls, summary, _ = self.invoke(["agent_failed", "runner_error", "check_failed"])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 6)
        self.assertIsNone(summary["stop_reason"])
        self.assertNotIn("max_capability_failures", summary["schedule"])

    def test_total_capability_limit_includes_failures_separated_by_success(self) -> None:
        code, calls, summary, stderr = self.invoke(["check_failed", None, "agent_timeout"], "--max-capability-failures", "2")
        self.assertEqual(code, 1)
        self.assertEqual(calls, ["S01", "S02", "S03"])
        self.assertEqual(summary["stop_reason"], "capability_failure_limit")
        self.assertEqual(summary["schedule"]["skipped_episodes"], 3)
        self.assertTrue(summary["schedule"]["stopped_early"])
        self.assertEqual(summary["schedule"]["max_capability_failures"], 2)
        self.assertEqual(summary["schedule"]["capability_failures"], 2)
        self.assertIn("STOP schedule", stderr)
        self.assertFalse(summary["acceptance"]["eligible"])

    def test_safety_stops_immediately_even_when_primary_failure_is_timeout(self) -> None:
        for failure in ("safety_violation", "agent_timeout"):
            with self.subTest(failure=failure):
                code, calls, summary, _ = self.invoke([failure], safety=True)
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), 1)
                self.assertEqual(summary["stop_reason"], "safety_violation")
                self.assertEqual(summary["schedule"]["skipped_episodes"], 5)

    def test_bounded_mode_stops_infrastructure_failure_without_spending_budget(self) -> None:
        for failure in ("runner_error", "setup_failed", "check_timeout", "agent_start_failed"):
            with self.subTest(failure=failure):
                code, calls, summary, _ = self.invoke([failure], "--max-capability-failures", "2")
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), 1)
                self.assertEqual(summary["stop_reason"], failure)
                self.assertEqual(summary["schedule"]["capability_failures"], 0)

    def test_bounded_mode_unknown_failure_is_not_guessed_as_capability(self) -> None:
        code, calls, summary, _ = self.invoke(["future_unknown_failure"], "--max-capability-failures", "2")
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary["stop_reason"], "future_unknown_failure")
        self.assertEqual(summary["schedule"]["capability_failures"], 0)

    def test_provider_and_leak_stop_reasons_keep_precedence_over_safety(self) -> None:
        for failure in ("provider_rate_limited", "endpoint_secret_leak"):
            with self.subTest(failure=failure):
                code, calls, summary, _ = self.invoke([failure], safety=True)
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), 1)
                self.assertEqual(summary["stop_reason"], failure)


if __name__ == "__main__":
    unittest.main()
