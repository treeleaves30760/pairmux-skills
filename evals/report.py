#!/usr/bin/env python3
"""Stdlib-only, descriptive multi-run eval report (never acceptance certification).

Recipes, from the repository root:
    python3 evals/report.py evals/runs/<run-a> evals/runs/<run-b>
    python3 evals/report.py --runs evals/runs/<run-a> --output /tmp/report.md \
        --json-output /tmp/report.json --seed 42
    python3 evals/report.py evals/runs/<run-a>/metrics.jsonl --seed 42

A JSONL input joins only adjacent summary.json and episodes/<episode_id>/result.json;
artifact-supplied paths are never followed. Run directories use metrics.jsonl when
present, otherwise metrics.py's episode_metrics (no second transcript parser).
Missing provenance creates an unknown, run-scoped cohort, excluded from pairing.
Pairs require the same scenario and explicit trial_id (or repeat), compatible
provenance except the terminal treatment, and success on BOTH sides. Ambiguous
repeated indices are not arbitrarily paired. Failures remain in outcome summaries.
Token measurements and chars/4 estimates are separate; missing usage is unknown.
Outputs are stdout unless explicitly selected, and cannot replace source artifacts.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import random
import sys
from urllib.parse import urlsplit, urlunsplit

_SPEC = importlib.util.spec_from_file_location("pairmux_report_metrics", Path(__file__).with_name("metrics.py"))
assert _SPEC and _SPEC.loader
metrics = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(metrics)

SCHEMA = "pairmux.eval.report.v1"
ENDPOINT_FIELDS = ("base_url", "provider", "model", "protocol", "context_tokens", "max_output_tokens", "effort", "output_limit_enforced")
MEASURES = (
    "wall_time_seconds", "agent_duration_seconds", "setup_duration_seconds",
    "discovery_duration_seconds", "tool_calls", "pairmux_calls", "tokens_in", "tokens_out",
    "sleep_calls", "duplicate_commands", "capture_pane_calls", "send_keys_calls", "pairmux_stub_hits",
)
TRANSCRIPT_MEASURES = MEASURES[4:]
EFFICIENCY = MEASURES[:2] + ("tool_calls", "tokens_in", "tokens_out")
INFRA = {
    "setup_start_failed", "setup_timeout", "setup_failed", "agent_start_failed",
    "check_start_failed", "check_timeout", "runner_error", "runner_exception",
    "control_cleanup_failed", "credential_cleanup_failed", "skill_discovery_failed", "provider_error",
    "endpoint_configuration_failed", "endpoint_artifact_sanitization_failed", "endpoint_infrastructure_unknown",
    "provider_auth_failed", "provider_rate_limited", "provider_unavailable",
}
CAPABILITY = {"agent_timeout", "agent_failed", "check_failed", "handoff_not_blocking"}
MISSING = object()


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def fail(context: str, message: str) -> None:
    raise ValueError(f"{context}: {message}")


def json_object(text: str, context: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("non-finite JSON number")

    def number(value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)
    except (ValueError, RecursionError):
        fail(context, "malformed JSON object (contents not shown)")
    if not isinstance(value, dict):
        fail(context, "record must be a JSON object")
    return value


def read_object(path: Path) -> dict:
    try:
        return json_object(path.read_text(encoding="utf-8"), str(path))
    except (OSError, UnicodeError):
        fail(str(path), "cannot read JSON artifact")


def validate(record: dict, context: str, identity: bool = True) -> None:
    for field in ("run_id", "episode_id"):
        value = record.get(field)
        if identity and (not isinstance(value, str) or not value or value in {".", ".."} or "/" in value or "\\" in value):
            fail(context, f"{field} must be a nonempty, single-component identifier")
    for field in ("scenario", "agent", "agent_version", "model", "model_variant", "terminal_harness", "provider", "pairmux_sha256", "skill_tree_sha256", "skill_md_sha256", "failure_class", "agent_observed_failure_class", "control_cleanup_failure_class"):
        if record.get(field) is not None and not isinstance(record[field], str):
            fail(context, f"{field} must be a string or null")
    for field in ("pass", "tokens_estimated", "safety_veto", "safety_violation", "endpoint_artifacts_scrubbed", "admin_done"):
        if record.get(field) is not None and not isinstance(record[field], bool):
            fail(context, f"{field} must be a boolean or null")
    for field in MEASURES + ("score", "raw_subgoal_score", "repeat", "timeout_seconds"):
        value = record.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            fail(context, f"{field} must be a finite nonnegative number or null")
        if field in {"score", "raw_subgoal_score"} and value is not None and value > 1:
            fail(context, f"{field} must be in [0, 1]")
    if record.get("repeat") is not None and (record["repeat"] < 1 or int(record["repeat"]) != record["repeat"]):
        fail(context, "repeat must be a positive integer")
    for field in ("endpoint", "terminal_harness_policy", "acceptance"):
        if record.get(field) is not None and not isinstance(record[field], dict):
            fail(context, f"{field} must be an object or null")
    for field in ("schema", "host_tmux", "pairmux", "skill"):
        if (record.get("terminal_harness_policy") or {}).get(field) is not None and not isinstance(record["terminal_harness_policy"][field], str):
            fail(context, f"terminal_harness_policy.{field} must be a string or null")
    if (record.get("acceptance") or {}).get("profile") is not None and not isinstance(record["acceptance"]["profile"], str):
        fail(context, "acceptance.profile must be a string or null")
    endpoint = record.get("endpoint")
    if endpoint is not None:
        for field in ("provider", "model", "protocol", "effort"):
            if endpoint.get(field) is not None and not isinstance(endpoint[field], str):
                fail(context, f"endpoint.{field} must be a string or null")
        if endpoint.get("output_limit_enforced") is not None and not isinstance(endpoint["output_limit_enforced"], bool):
            fail(context, "endpoint.output_limit_enforced must be a boolean or null")
        for field in ("context_tokens", "max_output_tokens"):
            value = endpoint.get(field)
            if value is not None and (type(value) is not int or value <= 0):
                fail(context, f"endpoint.{field} must be a positive integer or null")
    if "subgoals" in record and record["subgoals"] is not None:
        goals = record["subgoals"]
        if not isinstance(goals, list):
            fail(context, "subgoals must be an array")
        for goal in goals:
            if not isinstance(goal, dict) or not isinstance(goal.get("pass"), bool):
                fail(context, "each subgoal must be an object with a boolean pass")
            if not isinstance(goal.get("id"), str) or not isinstance(goal.get("detail", ""), str):
                fail(context, "subgoal id/detail must be strings")
    if record.get("scenario_source_sha256") is not None:
        fixture = record["scenario_source_sha256"]
        if not isinstance(fixture, (str, dict)) or (isinstance(fixture, dict) and any(not isinstance(value, str) for value in fixture.values())):
            fail(context, "scenario_source_sha256 must be a hash or hash object")
    for field in ("provider_status", "provider_http_status"):
        if record.get(field) is not None and type(record[field]) not in {str, int}:
            fail(context, f"{field} must be a string or integer")
    if "safety_violations" in record:
        value = record["safety_violations"]
        if value is not None and not isinstance(value, list) and (type(value) is not int or value < 0):
            fail(context, "safety_violations must be an array, nonnegative count, or null")
    for field in ("trial_id", "pairing_id"):
        if record.get(field) is not None and (type(record[field]) not in {str, int} or record[field] == ""):
            fail(context, f"{field} must be a nonempty string or integer")


def pick(field: str, *records: dict):
    for record in records:
        if field in record:
            return record[field]
    return MISSING


def safe_url(value: object, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        fail(context, "endpoint.base_url must be a string or null")
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError()
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        if port and (parts.scheme.lower(), port) not in {("http", 80), ("https", 443)}:
            host += f":{port}"
        # Never emit credentials, query parameters, fragments, or arbitrary endpoint keys.
        return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/"), "", ""))
    except ValueError:
        fail(context, "endpoint.base_url must be an HTTP(S) URL (contents not shown)")


def endpoint_core(endpoint: dict | None, context: str) -> dict | None:
    if endpoint is None:
        return None
    core = {field: endpoint.get(field) for field in ENDPOINT_FIELDS}
    core["base_url"] = safe_url(core["base_url"], context)
    return core


def provenance(row: dict, result: dict, summary: dict, raw: dict, context: str) -> dict:
    missing = []
    data = {}
    required = ("agent", "agent_version", "model", "model_variant", "provider", "skill_tree_sha256", "skill_md_sha256", "pairmux_sha256", "timeout_seconds")
    for field in required:
        value = pick(field, result, summary, raw)
        if field in {"skill_tree_sha256", "skill_md_sha256"} and value == "not-installed" and row["terminal_harness"] in {"shell", "rawtmux"}:
            value = summary.get(field, MISSING)  # Compare source hashes, not baseline's absent installation.
        nullable = field == "model_variant"
        if value is MISSING or (not value and not nullable):
            missing.append(field)
            value = None
        data[field] = value
    endpoint = pick("endpoint", result, summary, raw)
    if endpoint is MISSING:
        missing.append("endpoint")
        data["endpoint"] = None
    elif endpoint is None:  # Explicitly not an endpoint-backed agent.
        data["endpoint"] = None
    else:
        data["endpoint"] = endpoint_core(endpoint, context)
        for field in data["endpoint"]:
            if field not in endpoint and field != "output_limit_enforced":
                missing.append(f"endpoint.{field}")
        for field in ("base_url", "provider", "model", "protocol"):
            if not data["endpoint"].get(field):
                missing.append(f"endpoint.{field}")
    policy = pick("terminal_harness_policy", result, summary, raw)
    data["terminal_harness_policy"] = {field: policy.get(field) if isinstance(policy, dict) else None for field in ("schema", "host_tmux", "pairmux", "skill")}
    for field, value in data["terminal_harness_policy"].items():
        if not isinstance(value, str) or not value:
            missing.append(f"terminal_harness_policy.{field}")
    comparable_fixtures = summary.get("fixture_sha256") or {}
    fixture = pick("scenario_source_sha256", result, raw)
    if fixture is MISSING:
        fixture = comparable_fixtures.get(row["scenario"])
    elif row["scenario"] in comparable_fixtures and comparable_fixtures[row["scenario"]] != fixture:
        fail(context, "result/summary disagree on fixture provenance")
    if not fixture:
        missing.append("fixture_sha256")
        data["fixture_sha256"] = None
    else:
        if not isinstance(fixture, (str, dict)) or (isinstance(fixture, dict) and any(not isinstance(value, str) for value in fixture.values())):
            fail(context, "fixture provenance must be a hash or hash object")
        data["fixture_sha256"] = hashlib.sha256(canonical(fixture).encode()).hexdigest()
    acceptance = summary.get("acceptance") or result.get("acceptance") or raw.get("acceptance") or {}
    data["acceptance_profile"] = acceptance.get("profile")
    if not isinstance(data["acceptance_profile"], str) or not data["acceptance_profile"]:
        missing.append("acceptance_profile")
    data["codex_sandbox"] = summary.get("codex_sandbox")
    if data["agent"] == "codex" and not data["codex_sandbox"]:
        missing.append("codex_sandbox")
    if not result:
        missing.append("result.json")
    if not summary:
        missing.append("summary.json")
    if row["terminal_harness"] == "unknown":
        missing.append("terminal_harness")
    if row["scenario"] == "unknown":
        missing.append("scenario")
    data["missing"] = sorted(set(missing))
    data["unknown_run_id"] = row["run_id"] if missing else None
    return data


def failure_status(row: dict, safety: bool) -> tuple[str, str]:
    if safety:
        return "safety", "safety_violation"
    status = row.get("agent_observed_failure_class") or row.get("failure_class") or row.get("control_cleanup_failure_class")
    provider = row.get("provider_http_status", row.get("provider_status"))
    aliases = {"429": "provider_rate_limited", "401": "provider_auth_failed", "403": "provider_auth_failed", "rate_limited": "provider_rate_limited", "auth_failed": "provider_auth_failed", "unavailable": "provider_unavailable"}
    normalized = str(provider).lower().replace("-", "_") if provider is not None else ""
    if normalized in {"provider_auth_failed", "provider_rate_limited", "provider_unavailable"}:
        status = normalized
    elif normalized in aliases:
        status = aliases[normalized]
    elif status is None and normalized == "error":
        status = "provider_error"
    elif normalized.isdigit() and 500 <= int(normalized) <= 599:
        status = "provider_unavailable"
    if status in INFRA:
        return "infrastructure", status
    if status in CAPABILITY:
        return "capability", status
    if status:
        return "unknown", "unclassified_failure"
    return ("none", "none") if row.get("pass") is True else ("unknown", "unclassified_failure")


def observation(raw: dict, result: dict, summary: dict, context: str) -> dict:
    for field in ("run_id", "episode_id", "scenario", "agent", "model", "model_variant", "terminal_harness"):
        if field in raw and field in result and raw[field] != result[field]:
            fail(context, f"metrics/result disagree on {field}")
    for field in ("run_id", "agent", "agent_version", "model", "model_variant", "terminal_harness", "endpoint", "terminal_harness_policy", "pairmux_sha256", "skill_tree_sha256", "skill_md_sha256"):
        if field in result and field in summary and result[field] != summary[field]:
            if field == "endpoint" and endpoint_core(result[field], context) == endpoint_core(summary[field], context):
                continue
            if field in {"skill_tree_sha256", "skill_md_sha256"} and result[field] == "not-installed" and result.get("terminal_harness") in {"shell", "rawtmux"}:
                continue
            fail(context, f"result/summary disagree on {field}")
    joined = dict(raw)
    joined.update(result)  # Actual result is authoritative for outcomes and timing.
    row = {field: joined.get(field) for field in ("run_id", "episode_id", "repeat", "pass")}
    row["scenario"] = joined.get("scenario") or "unknown"
    row["terminal_harness"] = joined.get("terminal_harness", summary.get("terminal_harness")) or "unknown"
    row["trial_id"] = joined.get("trial_id", joined.get("pairing_id", summary.get("trial_id")))
    goals = joined.get("subgoals") or []
    safety_goals = [goal for goal in goals if goal.get("detail", "").startswith("safety:") or goal["id"] == "secret_never_guessed"]
    safety_fields = ("safety_violation", "safety_violations", "safety_veto", "endpoint_artifacts_scrubbed")
    secret_leak = joined.get("failure_class") == "endpoint_secret_leak"
    row["safety_known"] = bool(safety_goals) or secret_leak or any(joined.get(field) is not None for field in safety_fields)
    row["safety_veto"] = secret_leak or any(not goal["pass"] for goal in safety_goals) or any(bool(joined.get(field)) for field in safety_fields)
    row["raw_subgoal_score"] = joined.get("raw_subgoal_score", joined.get("score"))
    row["score"] = 0.0 if row["safety_veto"] else joined.get("score")
    capability = [float(goal["pass"]) for goal in goals if goal.get("detail", "").startswith("capability:")]
    row["capability_score"] = math.fsum(capability) / len(capability) if capability else None
    row["admin_done"] = joined.get("admin_done")
    if row["admin_done"] is None:
        marker = [goal["pass"] for goal in goals if goal["id"] == "done_marker"]
        row["admin_done"] = all(marker) if marker else None
    row["failure_kind"], row["failure_status"] = failure_status(joined, row["safety_veto"])
    if row["failure_kind"] in {"safety", "infrastructure", "capability"} or (row["failure_kind"] == "unknown" and row["pass"] is True):
        row["pass"] = False
    row["measures"] = {}
    # Historical exception fallbacks wrote 0.0 without measuring episode elapsed time.
    legacy_wall_placeholder = (
        joined.get("wall_time_seconds") == 0
        and joined.get("failure_class") == "runner_error"
        and row["episode_id"].endswith("-runner-error")
        and all(joined.get(field) is None for field in (
            "started_at", "finished_at", "timeout_seconds", "agent_duration_seconds",
            "setup_duration_seconds", "discovery_duration_seconds",
        ))
        and not any(joined.get(field) == "measured" for field in (
            "wall_time_seconds_source", "wall_time_source", "duration_source", "timing_source",
        ))
    )
    for field in MEASURES:
        value = joined.get(field)
        source = "measured" if value is not None else "unknown"
        if field == "wall_time_seconds" and legacy_wall_placeholder:
            source = "unknown"
        if field.startswith("tokens_"):
            source = joined.get(f"{field}_source", joined.get("tokens_source"))
            if source is None:
                flag = joined.get("tokens_estimated")
                source = "estimated" if flag is True else "measured" if flag is False else "unknown"
            if source not in {"measured", "estimated", "unknown"}:
                fail(context, f"{field}_source must be measured, estimated, or unknown")
            if value is None or (source == "estimated" and value == 0):
                source = "unknown"  # metrics.py's estimated input=0 is not an observation.
        row["measures"][field] = {"value": value if source != "unknown" else None, "source": source}
    row["recorded_acceptance_eligible"] = (summary.get("acceptance") or {}).get("eligible")
    if row["recorded_acceptance_eligible"] is not None and not isinstance(row["recorded_acceptance_eligible"], bool):
        fail(context, "acceptance.eligible must be a boolean or null")
    row["provenance"] = provenance(row, result, summary, raw, context)
    return row


def load_observations(inputs: list[Path]) -> tuple[list[dict], int, set[Path]]:
    rows, signatures, sources = {}, {}, set()
    duplicates = 0
    for source in inputs:
        source = source.expanduser().resolve()
        root = source if source.is_dir() else source.parent
        if not source.is_dir() and source.suffix != ".jsonl":
            fail(str(source), "input must be a run directory or metrics JSONL file")
        summary_path = root / "summary.json"
        summary = read_object(summary_path) if summary_path.exists() else {}
        if summary:
            validate(summary, str(summary_path), identity=False)
            for field in ("fixture_sha256",):
                if not isinstance(summary.get(field, {}), dict):
                    fail(str(summary_path), f"{field} must be an object")
            if summary.get("results") is not None:
                if not isinstance(summary["results"], list):
                    fail(str(summary_path), "results must be an array")
                for record in summary["results"]:
                    if not isinstance(record, dict):
                        fail(str(summary_path), "each result must be an object")
                    validate(record, str(summary_path))
            sources.add(summary_path.resolve())
        jsonl = root / "metrics.jsonl" if source.is_dir() else source
        if jsonl.is_file():
            sources.add(jsonl.resolve())
            try:
                text = jsonl.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                fail(str(jsonl), "cannot read metrics JSONL")
            records = [(json_object(line, f"{jsonl}:line {number}"), f"{jsonl}:line {number}") for number, line in enumerate(text.splitlines(), 1) if line.strip()]
        elif source.is_dir():
            episodes = root / "episodes"
            records = []
            if not episodes.is_dir():
                fail(str(source), "run has neither metrics.jsonl nor episodes/")
            for episode in sorted(episodes.iterdir()):
                path = episode / "result.json"
                if not episode.is_dir() or not path.is_file():
                    continue
                result = read_object(path)
                validate(result, str(path))
                raw = metrics.episode_metrics(episode)
                if raw is None:
                    fail(str(path), "metrics.py could not load the episode")
                transcript = episode / "transcript.jsonl"
                if not transcript.is_file() or not transcript.stat().st_size:
                    for field in TRANSCRIPT_MEASURES:
                        if field != "pairmux_calls":
                            raw[field] = None
                    raw["tokens_estimated"] = None
                if transcript.is_file():
                    sources.add(transcript.resolve())
                # Do not inherit metrics.py's historical default harness/score.
                for field in ("terminal_harness", "score"):
                    if field not in result:
                        raw.pop(field, None)
                records.append((raw, str(path)))
        else:
            fail(str(source), "metrics JSONL file does not exist")
        if not records:
            fail(str(source), "input contains no metrics records")
        for raw, context in records:
            validate(raw, context)
            result_path = root / "episodes" / raw["episode_id"] / "result.json"
            result = read_object(result_path) if result_path.is_file() else {}
            if result:
                validate(result, str(result_path))
                sources.add(result_path.resolve())
            if summary.get("run_id") is not None and summary["run_id"] != raw["run_id"]:
                fail(context, "metrics/summary disagree on run_id")
            row = observation(raw, result, summary, context)
            key = (row["run_id"], row["episode_id"])
            signature = canonical([raw, row])
            if key in rows:
                if signatures[key] != signature:
                    fail(context, "conflicting duplicate (run_id, episode_id)")
                duplicates += 1
            else:
                rows[key], signatures[key] = row, signature
    return [rows[key] for key in sorted(rows)], duplicates, sources


def estimate(values: list[float], total: int, seed: int, samples: int, minimum: int) -> dict:
    values = sorted(float(value) for value in values)
    n = len(values)
    mean = math.fsum(values) / n if n else None
    ci = None
    note = "unknown" if not n else "n=1; mean only (bootstrap would be degenerate)"
    if n > 1:
        rng = random.Random(seed)
        boot = sorted(math.fsum(rng.choices(values, k=n)) / n for _ in range(samples))
        def percentile(p):
            position = p * (samples - 1)
            lo = int(position)
            hi = min(lo + 1, samples - 1)
            return boot[lo] + (boot[hi] - boot[lo]) * (position - lo)
        ci = [percentile(0.025), percentile(0.975)]
        note = "degenerate bootstrap interval; not evidence of certainty" if ci[0] == ci[1] else "descriptive percentile bootstrap"
    return {"n": n, "unknown": total - n, "mean": mean, "ci95": ci, "ci_note": note,
            "label": "unknown" if not n else "exploratory" if n < minimum else "descriptive (not acceptance)"}


def cohort_id(provenance: dict, harness: str | None = None) -> str:
    return hashlib.sha256(canonical([provenance, harness]).encode()).hexdigest()


def comparisons(rows: list[dict], summarize) -> tuple[list[dict], int]:
    buckets = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    excluded = 0
    for row in rows:
        if row["provenance"]["missing"]:
            excluded += 1
            continue
        if row["trial_id"] is None and row["repeat"] is None:
            excluded += 1
            continue
        comparable = dict(row["provenance"])
        comparable["terminal_harness_policy"] = {field: comparable["terminal_harness_policy"][field] for field in ("schema", "host_tmux")}
        key = (row["scenario"], canonical(comparable))
        trial = canonical(["trial_id", row["trial_id"]]) if row["trial_id"] is not None else canonical(["repeat", row["repeat"]])
        buckets[key][trial][row["terminal_harness"]].append(row)
    output = []
    for (scenario, cohort), trials in sorted(buckets.items()):
        harnesses = sorted({harness for trial in trials.values() for harness in trial})
        for left, right in itertools.combinations(harnesses, 2):
            counts = Counter()
            pairs = []
            for trial, candidates in sorted(trials.items()):
                a, b = candidates.get(left, []), candidates.get(right, [])
                if len(a) > 1 or len(b) > 1:
                    counts["ambiguous"] += 1
                elif not a or not b:
                    counts["unmatched"] += 1
                elif any(row["pass"] is False for row in (a[0], b[0])):
                    counts["failed"] += 1
                elif any(row["pass"] is not True or row["failure_kind"] != "none" for row in (a[0], b[0])):
                    counts["unknown_outcome"] += 1
                else:
                    pairs.append((trial, a[0], b[0]))
            deltas = {}
            for field in EFFICIENCY:
                deltas[field] = {}
                for source in ("measured", "estimated"):
                    values = [b["measures"][field]["value"] - a["measures"][field]["value"] for _, a, b in pairs if a["measures"][field]["source"] == b["measures"][field]["source"] == source]
                    deltas[field][source] = summarize(values, len(pairs))
            output.append({"scenario": scenario, "cohort_id": cohort_id(json.loads(cohort)), "left": left, "right": right,
                           "candidate_trials": len(trials), "matched_successful": len(pairs),
                           "excluded": {field: counts[field] for field in ("failed", "unmatched", "ambiguous", "unknown_outcome")},
                           "pairs": [{"trial": json.loads(trial), "left": [a["run_id"], a["episode_id"]], "right": [b["run_id"], b["episode_id"]]} for trial, a, b in pairs],
                           "delta_right_minus_left": deltas})
    return output, excluded


def build_report(rows: list[dict], *, seed: int = 0, bootstrap_samples: int = 2000, min_samples: int = 5, duplicates: int = 0) -> dict:
    if bootstrap_samples < 100 or min_samples < 2:
        raise ValueError("bootstrap_samples must be >=100 and min_samples >=2")
    def summarize(values, total):
        return estimate(values, total, seed, bootstrap_samples, min_samples)
    buckets = defaultdict(list)
    for row in rows:
        key = (row["scenario"], row["terminal_harness"], canonical(row["provenance"]))
        buckets[key].append(row)
    groups = []
    for (scenario, harness, provenance_json), items in sorted(buckets.items()):
        n = len(items)
        data = json.loads(provenance_json)
        group = {"scenario": scenario, "terminal_harness": harness, "cohort_id": cohort_id(data, harness), "cohort": data,
                 "cohort_status": "unknown" if data["missing"] else "known", "n": n,
                 "runs": sorted({row["run_id"] for row in items}),
                 "pass_rate": summarize([float(row["pass"]) for row in items if row["pass"] is not None], n),
                 "passed": sum(row["pass"] is True for row in items),
                 "failures": {kind: sum(row["failure_kind"] == kind for row in items) for kind in ("infrastructure", "capability", "safety", "unknown")},
                 "failure_statuses": dict(sorted(Counter(row["failure_status"] for row in items).items())),
                 "safety_veto": sum(row["safety_veto"] for row in items), "safety_unknown": sum(not row["safety_known"] for row in items),
                 "recorded_acceptance": {"eligible": sum(row["recorded_acceptance_eligible"] is True for row in items), "ineligible": sum(row["recorded_acceptance_eligible"] is False for row in items), "unknown": sum(row["recorded_acceptance_eligible"] is None for row in items)}}
        for field in ("score", "raw_subgoal_score", "capability_score", "admin_done"):
            group[field] = summarize([row[field] for row in items if row[field] is not None], n)
        group["measures"] = {}
        for field in MEASURES:
            group["measures"][field] = {source: summarize([row["measures"][field]["value"] for row in items if row["measures"][field]["source"] == source], n) for source in ("measured", "estimated")}
            group["measures"][field]["unknown"] = sum(row["measures"][field]["source"] == "unknown" for row in items)
        groups.append(group)
    paired, excluded = comparisons(rows, summarize)
    return {"schema": SCHEMA, "seed": seed, "bootstrap_samples": bootstrap_samples, "min_samples": min_samples,
            "episodes": len(rows), "duplicates_removed": duplicates,
            "scope": {"agents": sorted({row["provenance"]["agent"] or "unknown" for row in rows}),
                      "terminal_harnesses": sorted({row["terminal_harness"] for row in rows}),
                      "endpoint_models": sorted({row["provenance"]["endpoint"]["model"] for row in rows if row["provenance"]["endpoint"] and row["provenance"]["endpoint"].get("model")}),
                      "recorded_model_identifiers": sorted({(row["provenance"]["endpoint"] or {}).get("model") or row["provenance"]["model"] or "unknown" for row in rows})},
            "groups": groups, "comparisons": paired, "pairing_excluded_missing_provenance_or_trial": excluded}


def cell(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "&#124;").replace("`", "&#96;").replace("\r", " ").replace("\n", " ")


def statistic(value: dict) -> str:
    if value["mean"] is None:
        return "unknown (n=0)"
    text = f"{value['mean']:.3f} (n={value['n']})"
    if value["ci95"] is not None:
        text += f" [{value['ci95'][0]:.3f}, {value['ci95'][1]:.3f}]"
        if value["ci95"][0] == value["ci95"][1]:
            text += "; degenerate"
    else:
        text += "; mean only"
    return text + ("; exploratory" if value["label"] == "exploratory" else "")


def render_markdown(report: dict) -> str:
    lines = ["# Multi-run eval report", "", "Descriptive/calibration only; **not acceptance certification**.",
             f"Episodes: {report['episodes']}; duplicates removed: {report['duplicates_removed']}. No inference about unobserved episodes.",
             f"Seed: {report['seed']}; bootstrap draws: {report['bootstrap_samples']}; exploratory below n={report['min_samples']}.",
             "Intervals are 95% percentile bootstrap of observed episodes, not causal or independence guarantees. n=1 is mean-only; degenerate intervals do not establish certainty.",
             "Agent harnesses: " + cell(", ".join(report["scope"]["agents"])) + ". Recorded model identifiers (not independent model replicas): " + cell(", ".join(report["scope"]["recorded_model_identifiers"])) + ".", "",
             "Reported endpoint models: " + cell(", ".join(report["scope"]["endpoint_models"]) or "unknown/not endpoint-backed") + ". Three agent harnesses do not constitute three models; n=1 groups are one-trial calibration.", "",
             "## Outcomes (all observed episodes, including infrastructure failures)", "",
             "| scenario | terminal harness | cohort | n | passed / known | pass rate [CI] | score [CI] | infra / capability / safety / unknown |",
             "|---|---|---|---:|---:|---|---|---|"]
    for group in report["groups"]:
        cohort = group["cohort_id"][:12] + (" (unknown)" if group["cohort_status"] == "unknown" else "")
        failures = " / ".join(str(group["failures"][kind]) for kind in ("infrastructure", "capability", "safety", "unknown"))
        lines.append("| " + " | ".join(map(cell, (group["scenario"], group["terminal_harness"], cohort, group["n"], f"{group['passed']} / {group['pass_rate']['n']}", statistic(group["pass_rate"]), statistic(group["score"]), failures))) + " |")
    lines += ["", "Safety violations veto pass and score to zero; raw subgoal score remains separate. Unknown pass/score values are not zeros.",
              "Capability means use only explicit `capability:` subgoals; admin DONE is separate, never an inferred historical capability pass.", "", "## Cohort details and measurements", ""]
    for group in report["groups"]:
        data = group["cohort"]
        lines += [f"### {group['cohort_id'][:12]} — {cell(group['scenario'])} / {cell(group['terminal_harness'])}",
                  f"Agent/model/variant: {cell(data['agent'])} / {cell(data['model'])} / {cell(data['model_variant'])}.",
                  "Provenance: `" + cell(canonical(data)) + "`.",
                  f"Recorded eligibility: {canonical(group['recorded_acceptance'])}; safety vetoes: {group['safety_veto']}; safety unknown: {group['safety_unknown']}.",
                  f"Raw subgoal score: {statistic(group['raw_subgoal_score'])}; explicit capability subset: {statistic(group['capability_score'])}; admin DONE: {statistic(group['admin_done'])}.", "",
                  "| metric | measured mean [CI] | estimated mean [CI] | unknown episodes |", "|---|---|---|---:|"]
        for field, measurements in group["measures"].items():
            lines.append(f"| {field} | {statistic(measurements['measured'])} | {statistic(measurements['estimated'])} | {measurements['unknown']} |")
        lines.append("")
    lines += ["## Matched successful efficiency only", "",
              "Pairs share scenario + trial_id (or repeat), with complete compatible provenance except terminal harness and its expected pairmux/skill treatment. Host-tmux policy is retained. Multiple candidates are ambiguous, not matched by order.",
              "Failed/unknown outcomes are excluded ONLY from this paired efficiency section, not outcome denominators. Differences are right minus left (negative means fewer seconds/calls/tokens); measured and estimated tokens never mix.",
              f"Episodes excluded for missing provenance/trial: {report['pairing_excluded_missing_provenance_or_trial']}.", ""]
    if not report["comparisons"]:
        lines.append("No eligible cross-harness pairs.")
    for comparison in report["comparisons"]:
        lines += [f"### {cell(comparison['scenario'])}: {cell(comparison['left'])} → {cell(comparison['right'])} ({comparison['cohort_id'][:12]})",
                  f"Matched successful: {comparison['matched_successful']}/{comparison['candidate_trials']}; excluded: {canonical(comparison['excluded'])}.",
                  "Trial identifiers: `" + cell(canonical([pair["trial"] for pair in comparison["pairs"]])) + "`.", "",
                  "| metric delta | measured [CI] | estimated [CI] |", "|---|---|---|"]
        for field, sources in comparison["delta_right_minus_left"].items():
            lines.append(f"| {field} | {statistic(sources['measured'])} | {statistic(sources['estimated'])} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*", help="metrics JSONL files or run directories")
    parser.add_argument("--runs", nargs="+", action="append", default=[], metavar="PATH", help="additional explicit inputs")
    parser.add_argument("--output", type=Path, help="Markdown output file (default: stdout)")
    parser.add_argument("--json-output", "--json", type=Path, help="optional machine-readable report file")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--min-samples", type=int, default=5, help="descriptive/exploratory label boundary, NOT acceptance")
    args = parser.parse_args(argv)
    inputs = [Path(path) for path in args.inputs + list(itertools.chain.from_iterable(args.runs))]
    if not inputs:
        parser.error("at least one explicit input is required")
    try:
        rows, duplicates, sources = load_observations(inputs)
        report = build_report(rows, seed=args.seed, bootstrap_samples=args.bootstrap_samples, min_samples=args.min_samples, duplicates=duplicates)
        destinations = [path.expanduser().resolve() for path in (args.output, args.json_output) if path is not None]
        if len(destinations) != len(set(destinations)):
            raise ValueError("Markdown and JSON output must be different files")
        for path in destinations:
            artifact_roots = [source.expanduser().resolve() if source.is_dir() else source.expanduser().resolve().parent for source in inputs if source.is_dir() or (source.parent / "summary.json").is_file() or (source.parent / "episodes").is_dir()]
            if path in sources or path in {Path(__file__).resolve(), Path(metrics.__file__).resolve()} or any(path == source.expanduser().resolve() for source in inputs) or (path.exists() and any(root in path.parents for root in artifact_roots)):
                fail(str(path), "output would overwrite a source artifact")
            if not path.parent.is_dir() or path.is_dir():
                fail(str(path), "output must name a file in an existing directory")
        markdown = render_markdown(report)
        if args.output is not None:
            args.output.expanduser().write_text(markdown, encoding="utf-8")
        else:
            sys.stdout.write(markdown)
        if args.json_output is not None:
            args.json_output.expanduser().write_text(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (ValueError, OSError, UnicodeError) as error:
        if isinstance(error, (OSError, UnicodeError)):
            parser.error("could not access an explicitly selected input/output artifact (contents not shown)")
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
