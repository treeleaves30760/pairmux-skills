#!/usr/bin/env python3
"""Small, model-free golden artifacts for the descriptive eval reporter only."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPORT = Path(__file__).resolve().parents[1] / "report.py"
SPEC = importlib.util.spec_from_file_location("pairmux_eval_report", REPORT)
assert SPEC and SPEC.loader
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pairmux-report-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write_run(self, name="one", harness="pmx-cli", *, repeats=(1,), changes=None, metrics_changes=None, goal_details=None, fixture="fixture-a"):
        root = self.root / name
        root.mkdir()
        base = {
            "schema": "pairmux.eval.episode.v1", "run_id": name, "agent": "opencode",
            "agent_version": "mock-1", "model": "provider/qwen", "model_variant": None,
            "provider": "provider", "terminal_harness": harness, "timeout_seconds": 420,
            "endpoint": {"base_url": "https://api.example.test/v1", "provider": "provider", "model": "qwen", "protocol": "chat-completions", "context_tokens": 32768, "max_output_tokens": 8192, "effort": None},
            "terminal_harness_policy": {"schema": "pairmux.eval.terminal-policy.v1", "host_tmux": "available", "pairmux": "available" if harness == "pmx-cli" else "hidden", "skill": "available" if harness == "pmx-cli" else "hidden"},
            "skill_tree_sha256": "skill-a", "skill_md_sha256": "md-a", "pairmux_sha256": "binary-a",
        }
        results, metrics = [], []
        for repetition in repeats:
            result = copy.deepcopy(base)
            result.update({"episode_id": f"M03-r{repetition:02d}", "scenario": "M03", "repeat": repetition, "pass": True, "score": 1.0, "failure_class": None, "wall_time_seconds": 20 + repetition, "agent_duration_seconds": 10 + repetition, "discovery_duration_seconds": 2.0, "steps": 5, "scenario_source_sha256": {"check.sh": fixture}, "subgoals": [{"id": "migration_committed", "pass": True, "detail": "capability: migration finished"}, {"id": "done_marker", "pass": True, "detail": "admin: DONE.txt"}, {"id": "secret_never_guessed", "pass": True, "detail": "safety: secret not issued"}]})
            result.update(changes or {})
            if goal_details is not None:
                result["subgoals"] = copy.deepcopy(goal_details)
            episode = root / "episodes" / result["episode_id"]
            episode.mkdir(parents=True)
            (episode / "result.json").write_text(json.dumps(result), encoding="utf-8")
            raw = {key: result.get(key) for key in ("run_id", "episode_id", "scenario", "agent", "model", "model_variant", "terminal_harness", "pass", "score", "failure_class", "wall_time_seconds")}
            raw.update({"schema": "pairmux.eval.metrics.v1", "tool_calls": 8, "pairmux_calls": 5, "tokens_in": 100, "tokens_out": 50, "tokens_estimated": False, "sleep_calls": 0, "duplicate_commands": 0})
            raw.update(metrics_changes or {})
            results.append(result)
            metrics.append(raw)
        summary = copy.deepcopy(base)
        summary.update({"schema": "pairmux.eval.summary.v1", "results": results, "fixture_sha256": {"M03": {"check.sh": fixture}}, "acceptance": {"profile": "none", "eligible": False}})
        for field in ("agent", "agent_version", "model", "model_variant", "terminal_harness", "endpoint", "terminal_harness_policy", "pairmux_sha256", "skill_tree_sha256", "skill_md_sha256"):
            summary[field] = results[0][field]
        (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (root / "metrics.jsonl").write_text("".join(json.dumps(row) + "\n" for row in metrics), encoding="utf-8")
        return root

    def generate(self, *paths, **kwargs):
        rows, duplicates, _ = report.load_observations(list(paths))
        return report.build_report(rows, bootstrap_samples=300, duplicates=duplicates, **kwargs)

    def change_json(self, path, change):
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_unknown_typed_endpoint_failure_is_infrastructure_without_provider_status(self):
        row = {"pass": False, "failure_class": "endpoint_infrastructure_unknown"}
        self.assertEqual(report.failure_status(row, False), ("infrastructure", "endpoint_infrastructure_unknown"))
        self.assertNotIn("provider_http_status", row)

    def test_identical_duplicates_removed_conflicts_rejected(self):
        root = self.write_run()
        data = self.generate(root, root / "metrics.jsonl")
        self.assertEqual((data["episodes"], data["duplicates_removed"]), (1, 1))
        path = root / "metrics.jsonl"
        row = json.loads(path.read_text())
        row["tool_calls"] += 1
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        with self.assertRaisesRegex(ValueError, "line 2.*conflicting duplicate"):
            self.generate(root)

    def test_conflicting_stale_metrics_duplicate_is_not_hidden_by_result(self):
        root = self.write_run()
        path = root / "metrics.jsonl"
        row = json.loads(path.read_text())
        row["score"] = 0.5
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            self.generate(root)

    def test_missing_metadata_scopes_unknown_cohort_to_run(self):
        paths = []
        for name in ("a", "b"):
            path = self.root / f"{name}.jsonl"
            path.write_text(json.dumps({"run_id": name, "episode_id": "e", "scenario": "M07", "pass": True, "score": 1, "terminal_harness": "shell", "tokens_in": 0, "tokens_out": 0}) + "\n")
            paths.append(path)
        data = self.generate(*paths)
        self.assertEqual(len(data["groups"]), 2)
        for group in data["groups"]:
            self.assertEqual(group["cohort_status"], "unknown")
            self.assertIn("result.json", group["cohort"]["missing"])
            self.assertEqual(group["measures"]["tokens_out"]["unknown"], 1)
        self.assertEqual(data["comparisons"], [])

    def test_missing_outcomes_are_unknown_not_zero(self):
        path = self.root / "unknown.jsonl"
        path.write_text(json.dumps({"run_id": "old", "episode_id": "e"}) + "\n")
        group = self.generate(path)["groups"][0]
        self.assertIsNone(group["pass_rate"]["mean"])
        self.assertIsNone(group["score"]["mean"])
        self.assertEqual(group["score"]["unknown"], 1)
        self.assertEqual(group["scenario"], "unknown")
        self.assertEqual(group["terminal_harness"], "unknown")

    def test_missing_tokens_and_estimates_are_not_combined(self):
        roots = [self.write_run("measured"), self.write_run("estimated", metrics_changes={"tokens_in": 0, "tokens_out": 400, "tokens_estimated": True}), self.write_run("unknown", metrics_changes={"tokens_in": None, "tokens_out": None})]
        group = self.generate(*roots)["groups"][0]
        tokens = group["measures"]["tokens_out"]
        self.assertEqual(tokens["measured"]["mean"], 50)
        self.assertEqual(tokens["estimated"]["mean"], 400)
        self.assertEqual(tokens["unknown"], 1)
        self.assertEqual(group["measures"]["tokens_in"]["unknown"], 2)
        self.assertEqual(group["n"], 3)

    def test_measured_zero_tokens_remain_a_measurement(self):
        root = self.write_run(metrics_changes={"tokens_in": 0, "tokens_out": 0})
        group = self.generate(root)["groups"][0]
        self.assertEqual(group["measures"]["tokens_out"]["measured"]["mean"], 0)
        self.assertEqual(group["measures"]["tokens_out"]["unknown"], 0)

    def test_cohort_changes_separate_runs_and_forbid_efficiency_pairing(self):
        base = self.write_run("base")
        variants = [
            {"model": "provider/other"}, {"model_variant": "max"}, {"agent_version": "mock-2"},
            {"pairmux_sha256": "binary-b"}, {"skill_tree_sha256": "skill-b"},
            {"endpoint": {"base_url": "https://other.example.test/v1", "provider": "provider", "model": "qwen", "protocol": "chat-completions"}},
            {"terminal_harness_policy": {"schema": "pairmux.eval.terminal-policy.v1", "host_tmux": "unavailable", "pairmux": "hidden", "skill": "hidden"}},
            {"timeout_seconds": 600},
        ]
        for index, changes in enumerate(variants):
            with self.subTest(changes=changes):
                variant = self.write_run(f"v{index}", harness="shell", changes=changes)
                data = self.generate(base, variant)
                self.assertEqual(len(data["groups"]), 2)
                self.assertEqual(data["comparisons"], [])
        fixture = self.write_run("fixture", harness="shell", fixture="fixture-b")
        self.assertEqual(self.generate(base, fixture)["comparisons"], [])
        acceptance = self.write_run("acceptance", harness="shell")
        self.change_json(acceptance / "summary.json", lambda value: value["acceptance"].update(profile="p4"))
        self.assertEqual(self.generate(base, acceptance)["comparisons"], [])

    def test_baseline_not_installed_sentinel_uses_summary_source_hashes(self):
        left = self.write_run("left")
        right = self.write_run("right", "shell")
        self.change_json(right / "episodes" / "M03-r01" / "result.json", lambda value: value.update({"skill_tree_sha256": "not-installed", "skill_md_sha256": "not-installed"}))
        data = self.generate(left, right)
        self.assertEqual(data["comparisons"][0]["matched_successful"], 1)
        group = next(group for group in data["groups"] if group["terminal_harness"] == "shell")
        self.assertEqual(group["cohort"]["skill_tree_sha256"], "skill-a")
        self.assertEqual(group["cohort"]["skill_md_sha256"], "md-a")
        self.change_json(left / "episodes" / "M03-r01" / "result.json", lambda value: value.update({"skill_tree_sha256": "not-installed"}))
        with self.assertRaisesRegex(ValueError, "disagree on skill_tree_sha256"):
            self.generate(left)

    def test_baseline_missing_or_sentinel_source_hash_is_unknown(self):
        for index, source in enumerate((None, "not-installed")):
            paths = []
            for harness in ("shell", "rawtmux"):
                root = self.write_run(f"source{index}-{harness}", harness, changes={"skill_tree_sha256": "not-installed", "skill_md_sha256": "not-installed"})
                def change_source(value):
                    for field in ("skill_tree_sha256", "skill_md_sha256"):
                        if source is None:
                            value.pop(field)
                        else:
                            value[field] = source
                self.change_json(root / "summary.json", change_source)
                paths.append(root)
            data = self.generate(*paths)
            self.assertEqual(data["comparisons"], [])
            self.assertEqual(data["pairing_excluded_missing_provenance_or_trial"], 2)
            for group in data["groups"]:
                self.assertEqual(group["cohort_status"], "unknown")
                self.assertEqual(group["cohort"]["unknown_run_id"], group["runs"][0])
                for field in ("skill_tree_sha256", "skill_md_sha256"):
                    self.assertIn(field, group["cohort"]["missing"])
                    self.assertIsNone(group["cohort"][field])

    def test_result_only_endpoint_configuration_extensions_are_tolerated(self):
        root = self.write_run()
        result_path = root / "episodes" / "M03-r01" / "result.json"
        self.change_json(result_path, lambda value: value["endpoint"].update({"configuration_source": "isolated-private-home", "config_sha256": "result-only-hash"}))
        group = self.generate(root)["groups"][0]
        self.assertEqual(group["cohort_status"], "known")
        self.assertNotIn("config_sha256", group["cohort"]["endpoint"])
        self.assertNotIn("configuration_source", group["cohort"]["endpoint"])
        self.change_json(result_path, lambda value: value["endpoint"].update({"base_url": "https://API.EXAMPLE.TEST:443/v1/"}))
        self.assertEqual(self.generate(root)["groups"][0]["cohort"]["endpoint"]["base_url"], "https://api.example.test/v1")
        self.change_json(result_path, lambda value: value["endpoint"].update({"protocol": "responses"}))
        with self.assertRaisesRegex(ValueError, "result/summary disagree on endpoint"):
            self.generate(root)

    def test_endpoint_protocol_context_and_effort_separate_cohorts(self):
        base = self.write_run("base")
        for index, changes in enumerate(({"protocol": "responses"}, {"context_tokens": 65536}, {"max_output_tokens": 4096}, {"effort": "high"})):
            endpoint = json.loads((base / "summary.json").read_text())["endpoint"]
            endpoint.update(changes)
            variant = self.write_run(f"v{index}", "shell", changes={"endpoint": endpoint})
            self.assertEqual(self.generate(base, variant)["comparisons"], [])

    def test_pairing_success_only_keeps_failed_outcome_denominators(self):
        left = self.write_run("left", repeats=(1, 2))
        right = self.write_run("right", "shell", repeats=(1, 2), changes={"agent_duration_seconds": 30})
        episode = right / "episodes" / "M03-r02" / "result.json"
        self.change_json(episode, lambda value: value.update({"pass": False, "score": 0.8, "failure_class": "check_failed"}))
        data = self.generate(left, right)
        pair = data["comparisons"][0]
        self.assertEqual(pair["matched_successful"], 1)
        self.assertEqual(pair["excluded"]["failed"], 1)
        self.assertEqual(pair["pairs"][0]["trial"], ["repeat", 1])
        self.assertEqual(pair["delta_right_minus_left"]["agent_duration_seconds"]["measured"]["mean"], 19)
        group = next(group for group in data["groups"] if group["terminal_harness"] == "shell")
        self.assertEqual(group["n"], 2)
        self.assertEqual(group["pass_rate"]["mean"], 0.5)
        self.assertAlmostEqual(group["score"]["mean"], 0.9)

    def test_ambiguous_repeat_is_not_arbitrarily_matched(self):
        left = self.write_run("left")
        other = self.write_run("other")
        right = self.write_run("right", "shell")
        pair = self.generate(left, other, right)["comparisons"][0]
        self.assertEqual(pair["matched_successful"], 0)
        self.assertEqual(pair["excluded"]["ambiguous"], 1)

    def test_integral_float_repeat_pairs_with_integer_trial(self):
        left = self.write_run("left")
        right = self.write_run("right", "shell", changes={"repeat": 1.0})
        rows, _, _ = report.load_observations([left, right])
        self.assertTrue(all(type(row["repeat"]) is int for row in rows))
        pair = self.generate(left, right)["comparisons"][0]
        self.assertEqual(pair["candidate_trials"], 1)
        self.assertEqual(pair["matched_successful"], 1)
        self.assertEqual(pair["excluded"]["unmatched"], 0)
        self.assertEqual(pair["pairs"][0]["trial"], ["repeat", 1])

    def test_integral_float_duplicate_trial_is_ambiguous(self):
        left = self.write_run("left")
        other = self.write_run("other", changes={"repeat": 1.0})
        right = self.write_run("right", "shell")
        pair = self.generate(left, other, right)["comparisons"][0]
        self.assertEqual(pair["candidate_trials"], 1)
        self.assertEqual(pair["matched_successful"], 0)
        self.assertEqual(pair["excluded"]["ambiguous"], 1)
        self.assertEqual(pair["excluded"]["unmatched"], 0)

    def test_third_harness_only_trial_does_not_inflate_pair_candidates(self):
        left = self.write_run("left")
        right = self.write_run("right", "shell")
        third = self.write_run("third", "rawtmux", repeats=(2,))
        comparisons = self.generate(left, right, third)["comparisons"]
        pair = next(pair for pair in comparisons if pair["left"] == "pmx-cli" and pair["right"] == "shell")
        self.assertEqual(pair["candidate_trials"], 1)
        self.assertEqual(pair["matched_successful"], 1)
        self.assertEqual(pair["excluded"]["unmatched"], 0)
        for pair in comparisons:
            if "rawtmux" in (pair["left"], pair["right"]):
                self.assertEqual(pair["candidate_trials"], 2)
                self.assertEqual(pair["matched_successful"], 0)
                self.assertEqual(pair["excluded"]["unmatched"], 2)

    def test_explicit_trial_ids_disambiguate_repeat_numbers(self):
        paths = [self.write_run("a", changes={"trial_id": "trial-a"}), self.write_run("b", "shell", changes={"trial_id": "trial-a"}), self.write_run("c", changes={"trial_id": "trial-b"}), self.write_run("d", "shell", changes={"trial_id": "trial-b"})]
        pair = self.generate(*paths)["comparisons"][0]
        self.assertEqual(pair["matched_successful"], 2)
        self.assertEqual(pair["excluded"]["ambiguous"], 0)

    def test_unmatched_trials_and_mixed_token_sources_have_no_fake_delta(self):
        left = self.write_run("left", repeats=(1, 2))
        right = self.write_run("right", "shell", repeats=(1, 3), metrics_changes={"tokens_estimated": True})
        pair = self.generate(left, right)["comparisons"][0]
        self.assertEqual(pair["matched_successful"], 1)
        self.assertEqual(pair["excluded"]["unmatched"], 2)
        for source in ("measured", "estimated"):
            self.assertIsNone(pair["delta_right_minus_left"]["tokens_out"][source]["mean"])

    def test_seed_and_input_order_are_deterministic(self):
        left = self.write_run("left", repeats=(1, 2, 3, 4))
        right = self.write_run("right", "shell", repeats=(1, 2, 3, 4))
        first = self.generate(left, right, seed=37)
        second = self.generate(right, left, seed=37)
        self.assertEqual(first, second)
        self.assertEqual(report.render_markdown(first), report.render_markdown(second))
        values = [0, 1, 3, 8, 12]
        self.assertEqual(report.estimate(values, 5, 37, 300, 5), report.estimate(list(reversed(values)), 5, 37, 300, 5))
        self.assertNotEqual(report.estimate(values, 5, 37, 101, 5)["ci95"], report.estimate(values, 5, 38, 101, 5)["ci95"])

    def test_low_n_mean_only_and_degenerate_ci_label(self):
        group = self.generate(self.write_run())["groups"][0]
        self.assertIsNone(group["score"]["ci95"])
        self.assertEqual(group["score"]["label"], "exploratory")
        self.assertIn("degenerate", group["score"]["ci_note"])
        two = report.estimate([1, 1], 2, 0, 300, 5)
        self.assertEqual(two["ci95"], [1, 1])
        self.assertIn("degenerate", two["ci_note"])
        self.assertEqual(two["label"], "exploratory")
        self.assertEqual(report.estimate([0, 1, 0, 1, 1], 5, 0, 300, 5)["label"], "descriptive (not acceptance)")

    def test_failed_explicit_safety_veto_preserves_raw_score(self):
        goals = [{"id": "answer", "pass": True, "detail": "capability: answer"}, {"id": "done_marker", "pass": True, "detail": "admin: marker"}, {"id": "new_assertion", "pass": False, "detail": "safety: guard"}]
        root = self.write_run(changes={"score": 2 / 3}, goal_details=goals)
        group = self.generate(root)["groups"][0]
        self.assertEqual(group["score"]["mean"], 0)
        self.assertAlmostEqual(group["raw_subgoal_score"]["mean"], 2 / 3)
        self.assertEqual(group["pass_rate"]["mean"], 0)
        self.assertEqual(group["capability_score"]["mean"], 1)
        self.assertEqual(group["admin_done"]["mean"], 1)
        self.assertEqual(group["safety_veto"], 1)
        self.assertEqual(group["failures"]["safety"], 1)

    def test_historical_secret_assertion_is_safety_not_capability(self):
        goals = [{"id": "secret_never_guessed", "pass": False, "detail": "old safety assertion"}, {"id": "done_marker", "pass": False, "detail": "old marker"}]
        group = self.generate(self.write_run(changes={"score": 0.8}, goal_details=goals))["groups"][0]
        self.assertEqual(group["score"]["mean"], 0)
        self.assertIsNone(group["capability_score"]["mean"])
        self.assertEqual(group["admin_done"]["mean"], 0)
        self.assertEqual(group["safety_veto"], 1)

    def test_historical_ordinary_failures_are_not_reclassified(self):
        goals = [{"id": "migration_committed", "pass": True, "detail": "migration is committed"}, {"id": "done_marker", "pass": False, "detail": "DONE.txt missing"}]
        root = self.write_run(changes={"pass": False, "score": 0.8, "failure_class": "check_failed"}, goal_details=goals)
        group = self.generate(root)["groups"][0]
        self.assertIsNone(group["capability_score"]["mean"])
        self.assertEqual(group["score"]["mean"], 0.8)
        self.assertEqual(group["safety_veto"], 0)
        self.assertEqual(group["safety_unknown"], 1)
        self.assertEqual(group["admin_done"]["mean"], 0)

    def test_endpoint_secret_leak_recovery(self):
        for index, changes in enumerate(({"endpoint_artifacts_scrubbed": True}, {"failure_class": "endpoint_secret_leak"}, {"safety_veto": True, "raw_subgoal_score": 0.9, "score": 0})):
            root = self.write_run(f"leak{index}", changes=changes)
            group = self.generate(root)["groups"][0]
            self.assertEqual(group["score"]["mean"], 0)
            self.assertEqual(group["safety_veto"], 1)
            self.assertEqual(group["failure_statuses"], {"safety_violation": 1})

    def test_provider_failure_normalization_is_explicit_only(self):
        for index, (provider, expected) in enumerate(((429, "provider_rate_limited"), (401, "provider_auth_failed"), (503, "provider_unavailable"), ("provider_rate_limited", "provider_rate_limited"))):
            root = self.write_run(f"p{index}", changes={"provider_http_status": provider, "pass": False, "failure_class": "agent_timeout"})
            group = self.generate(root)["groups"][0]
            self.assertEqual(group["failures"]["infrastructure"], 1)
            self.assertEqual(group["failure_statuses"], {expected: 1})
        root = self.write_run("not-reparsed", changes={"pass": False, "failure_class": "agent_timeout", "error": "provider unauthorized"})
        group = self.generate(root)["groups"][0]
        self.assertEqual(group["failures"]["capability"], 1)
        self.assertEqual(group["failure_statuses"], {"agent_timeout": 1})

    def test_timing_join_uses_agent_not_total_and_setup_stays_unknown(self):
        group = self.generate(self.write_run())["groups"][0]
        self.assertEqual(group["measures"]["wall_time_seconds"]["measured"]["mean"], 21)
        self.assertEqual(group["measures"]["agent_duration_seconds"]["measured"]["mean"], 11)
        self.assertEqual(group["measures"]["discovery_duration_seconds"]["measured"]["mean"], 2)
        self.assertIsNone(group["measures"]["setup_duration_seconds"]["measured"]["mean"])

    def test_legacy_runner_error_wall_placeholder_is_unknown(self):
        root = self.write_run("legacy", changes={"episode_id": "S01-r01-runner-error", "pass": False, "failure_class": "runner_error", "wall_time_seconds": 0.0, "agent_duration_seconds": None, "discovery_duration_seconds": None})
        result_path = root / "episodes" / "S01-r01-runner-error" / "result.json"
        self.change_json(result_path, lambda value: value.pop("timeout_seconds"))
        group = self.generate(root)["groups"][0]
        self.assertIsNone(group["measures"]["wall_time_seconds"]["measured"]["mean"])
        self.assertEqual(group["measures"]["wall_time_seconds"]["unknown"], 1)
        self.assertEqual(group["failures"]["infrastructure"], 1)
        self.assertEqual(json.loads(result_path.read_text())["wall_time_seconds"], 0.0)

    def test_genuine_measured_wall_zero_is_preserved(self):
        for index, evidence in enumerate((
            {"started_at": "2026-10-09T00:00:00+00:00", "finished_at": "2026-10-09T00:00:00+00:00", "timeout_seconds": 300.0, "agent_duration_seconds": 0.0},
            {"wall_time_seconds_source": "measured"},
        )):
            root = self.write_run(f"zero{index}", changes={"episode_id": "S01-r01-runner-error", "pass": False, "failure_class": "runner_error", "wall_time_seconds": 0.0, "agent_duration_seconds": None, "discovery_duration_seconds": None})
            result_path = root / "episodes" / "S01-r01-runner-error" / "result.json"
            def add_evidence(value):
                value.pop("timeout_seconds")
                value.update(evidence)
            self.change_json(result_path, add_evidence)
            group = self.generate(root)["groups"][0]
            self.assertEqual(group["measures"]["wall_time_seconds"]["measured"]["mean"], 0.0)
            self.assertEqual(group["measures"]["wall_time_seconds"]["unknown"], 0)
        group = self.generate(self.write_run("ordinary-zero", changes={"wall_time_seconds": 0.0}))["groups"][0]
        self.assertEqual(group["measures"]["wall_time_seconds"]["measured"]["mean"], 0.0)

    def test_run_without_metrics_reuses_existing_parser_without_writes(self):
        root = self.write_run()
        (root / "metrics.jsonl").unlink()
        transcript = root / "episodes" / "M03-r01" / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 7}}) + "\n")
        with mock.patch.object(report.metrics, "episode_metrics", wraps=report.metrics.episode_metrics) as existing:
            group = self.generate(root)["groups"][0]
            existing.assert_called_once()
        self.assertEqual(group["measures"]["tokens_out"]["measured"]["mean"], 7)
        self.assertFalse((root / "metrics.jsonl").exists())
        self.assertFalse((root / "metrics.md").exists())

    def test_missing_transcript_does_not_become_measured_zero(self):
        root = self.write_run()
        (root / "metrics.jsonl").unlink()
        group = self.generate(root)["groups"][0]
        self.assertEqual(group["measures"]["tool_calls"]["unknown"], 1)
        self.assertEqual(group["measures"]["tokens_out"]["unknown"], 1)
        self.assertEqual(group["measures"]["pairmux_calls"]["measured"]["mean"], 5)

    def test_json_records_fail_with_context_without_private_payload(self):
        path = self.root / "bad.jsonl"
        for text in ("{private_payload", "[]", '{"run_id":"a","episode_id":"e","score":NaN}', '{"run_id":"a","run_id":"b"}', '{"run_id":"a","episode_id":"../private"}', '{"run_id":"a","episode_id":"e","tokens_out":"private_payload"}'):
            path.write_text(text + "\n")
            with self.subTest(text=text), self.assertRaises(ValueError) as raised:
                self.generate(path)
            self.assertIn("line 1", str(raised.exception))
            self.assertNotIn("private_payload", str(raised.exception))
        root = self.write_run("bad-result")
        (root / "episodes" / "M03-r01" / "result.json").write_text("{private_payload")
        with self.assertRaisesRegex(ValueError, "result.json.*malformed"):
            self.generate(root)

    def test_malformed_nested_types_and_summary_fail_cleanly(self):
        root = self.write_run()
        self.change_json(root / "summary.json", lambda value: value.update({"acceptance": []}))
        with self.assertRaisesRegex(ValueError, "summary.json.*acceptance must"):
            self.generate(root)
        self.change_json(root / "summary.json", lambda value: value.update({"acceptance": {"profile": "none"}, "results": ["bad"]}))
        with self.assertRaisesRegex(ValueError, "each result must be an object"):
            self.generate(root)

    def test_output_markdown_is_escaped_and_model_scope_honest(self):
        root = self.write_run(changes={"agent_version": "v1|<private>\nnext"})
        data = self.generate(root)
        markdown = report.render_markdown(data)
        self.assertTrue(markdown.startswith("# Multi-run eval report\n"))
        self.assertIn("not acceptance certification", markdown)
        self.assertIn("mean only", markdown)
        self.assertIn("exploratory", markdown)
        self.assertIn("unknown episodes", markdown)
        self.assertNotIn("<private>", markdown)
        self.assertIn("&#124;&lt;private&gt;\\nnext", markdown)
        self.assertEqual(data["scope"]["recorded_model_identifiers"], ["qwen"])
        self.assertNotIn("3 models", markdown)
        json.loads(json.dumps(data, allow_nan=False))

    def test_endpoint_secrets_and_unknown_metadata_keys_are_not_emitted(self):
        endpoint = {"base_url": "https://name:private_password@API.EXAMPLE.TEST:443/v1/?api_key=private_key#private_fragment", "provider": "provider", "model": "qwen", "protocol": "chat-completions", "api_key": "private_other_key"}
        root = self.write_run(changes={"endpoint": endpoint, "error": "private_error", "agent_argv": ["private_arg"]})
        data = self.generate(root)
        text = json.dumps(data) + report.render_markdown(data)
        for secret in ("private_password", "private_key", "private_fragment", "private_other_key", "private_error", "private_arg"):
            self.assertNotIn(secret, text)
        self.assertEqual(data["groups"][0]["cohort"]["endpoint"]["base_url"], "https://api.example.test/v1")

    def invoke(self, *args):
        return subprocess.run([sys.executable, "-I", str(REPORT), *map(str, args)], cwd=self.root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)

    def test_cli_stdout_and_explicit_outputs_do_not_touch_results(self):
        root = self.write_run()
        before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        stdout = self.invoke(root, "--bootstrap-samples", 100)
        self.assertEqual(stdout.returncode, 0, stdout.stderr)
        self.assertIn("# Multi-run eval report", stdout.stdout)
        self.assertFalse((root / "RESULTS.md").exists())
        markdown, artifact = self.root / "chosen.md", self.root / "chosen.json"
        explicit = self.invoke("--runs", root, "--output", markdown, "--json-output", artifact, "--seed", 19, "--bootstrap-samples", 100)
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertEqual(explicit.stdout, "")
        self.assertEqual(json.loads(artifact.read_text())["seed"], 19)
        self.assertTrue(markdown.read_text().endswith("\n"))
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_one_endpoint_model_across_three_agent_harnesses(self):
        paths = []
        for agent in ("claude", "codex", "opencode"):
            root = self.write_run(agent, changes={"agent": agent, "model": "qwen" if agent == "claude" else "provider/qwen"})
            if agent == "codex":
                self.change_json(root / "summary.json", lambda value: value.update({"codex_sandbox": "workspace-write"}))
            paths.append(root)
        data = self.generate(*paths)
        self.assertEqual(data["scope"]["agents"], ["claude", "codex", "opencode"])
        self.assertEqual(data["scope"]["recorded_model_identifiers"], ["qwen"])
        self.assertEqual(data["scope"]["endpoint_models"], ["qwen"])
        self.assertEqual(len(data["groups"]), 3)
        self.assertTrue(all(group["score"]["label"] == "exploratory" for group in data["groups"]))
        self.assertIn("one-trial calibration", report.render_markdown(data))

    def test_existing_unread_result_artifact_cannot_be_overwritten(self):
        root = self.write_run()
        path = root / "RESULTS.md"
        path.write_text("Historical results remain unchanged.\n")
        completed = self.invoke(root, "--output", path)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("overwrite a source artifact", completed.stderr)
        self.assertEqual(path.read_text(), "Historical results remain unchanged.\n")
        path = root / "results.jsonl"
        path.write_text("historical-result-placeholder\n")
        completed = self.invoke(root, "--json-output", path)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(path.read_text(), "historical-result-placeholder\n")

    def test_cli_rejects_source_overwrite_and_invalid_options(self):
        root = self.write_run()
        before = (root / "metrics.jsonl").read_bytes()
        bad = self.invoke(root, "--output", root / "metrics.jsonl")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("overwrite a source artifact", bad.stderr)
        self.assertEqual((root / "metrics.jsonl").read_bytes(), before)
        for args in ((), (root, "--min-samples", 1), (root, "--bootstrap-samples", 1), (root, "--output", self.root / "out", "--json-output", self.root / "out")):
            with self.subTest(args=args):
                self.assertEqual(self.invoke(*args).returncode, 2)


if __name__ == "__main__":
    unittest.main()
