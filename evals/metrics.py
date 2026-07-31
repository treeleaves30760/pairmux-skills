#!/usr/bin/env python3
"""Per-episode efficiency metrics for eval runs.

Reads a run directory produced by run.py, joins each episode's result.json
with measurements extracted from its agent transcript, and writes
metrics.jsonl plus a metrics.md comparison table. Token counts come from the
transcript's own usage records when the agent CLI reports them; otherwise a
chars/4 estimate is used and flagged.

Usage: python3 evals/metrics.py <run-root> [<run-root> ...]
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

SCHEMA = "pairmux.eval.metrics.v1"
SLEEP_RE = re.compile(r"(?<![\w./-])sleep\s+[0-9]")
CAPTURE_RE = re.compile(r"capture-pane")
SEND_KEYS_RE = re.compile(r"send-keys")
STUB_RE = re.compile(r"pairmux: command not found")


def iter_events(path: Path):
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def issued_content(events: list[dict]) -> list[str]:
    """Agent-issued content only (commands and assistant text), mirroring
    lib.sh's pmx_issued_content across the three transcript dialects."""
    issued: list[str] = []
    for event in events:
        kind = event.get("type")
        if kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    issued.append(json.dumps(block.get("input", {}), separators=(",", ":")))
                elif block.get("type") == "text":
                    issued.append(str(block.get("text", "")))
        elif kind == "tool_use" and event.get("part", {}).get("type") == "tool":
            value = event.get("part", {}).get("state", {}).get("input")
            if value is not None:
                issued.append(json.dumps(value, separators=(",", ":")))
        elif kind == "text":
            issued.append(str(event.get("part", {}).get("text", "")))
        elif kind in {"item.started", "item.completed"}:
            item = event.get("item", {})
            if item.get("type") == "command_execution" and kind == "item.started":
                issued.append(str(item.get("command", "")))
            elif kind == "item.completed" and item.get("type") == "agent_message":
                issued.append(str(item.get("text", "")))
    return issued


def issued_commands(events: list[dict]) -> list[str]:
    """Tool/command invocations only (no assistant prose)."""
    commands: list[str] = []
    for event in events:
        kind = event.get("type")
        if kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    commands.append(json.dumps(block.get("input", {}), separators=(",", ":")))
        elif kind == "tool_use" and event.get("part", {}).get("type") == "tool":
            value = event.get("part", {}).get("state", {}).get("input")
            if value is not None:
                commands.append(json.dumps(value, separators=(",", ":")))
        elif kind == "item.started" and event.get("item", {}).get("type") == "command_execution":
            commands.append(str(event.get("item", {}).get("command", "")))
    return commands


def usage_pairs(value: object) -> list[tuple[int, int]]:
    """Recursively collect {input*, output*} token-usage dicts."""
    found: list[tuple[int, int]] = []
    if isinstance(value, dict):
        keys = set(value)
        in_key = next((k for k in ("input_tokens", "input", "prompt_tokens") if k in keys), None)
        out_key = next(
            (k for k in ("output_tokens", "output", "completion_tokens") if k in keys), None
        )
        if in_key and out_key:
            tokens_in, tokens_out = value.get(in_key), value.get(out_key)
            if isinstance(tokens_in, int) and isinstance(tokens_out, int):
                found.append((tokens_in, tokens_out))
        for child in value.values():
            found.extend(usage_pairs(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(usage_pairs(child))
    return found


def extract_tokens(events: list[dict], transcript: Path) -> tuple[int, int, bool]:
    """(tokens_in, tokens_out, estimated). Prefer a terminal result/turn usage
    record; else sum per-event records; else estimate chars/4."""
    for event in reversed(events):
        if event.get("type") in {"result", "turn.completed"}:
            pairs = usage_pairs(event)
            if pairs:
                best = max(pairs, key=lambda pair: pair[0] + pair[1])
                return best[0], best[1], False
    totals = [pair for event in events for pair in usage_pairs(event)]
    if totals:
        return sum(p[0] for p in totals), sum(p[1] for p in totals), False
    try:
        chars = transcript.stat().st_size
    except OSError:
        chars = 0
    estimate = math.ceil(chars / 4)
    return 0, estimate, True


def episode_metrics(episode_dir: Path) -> dict | None:
    result_path = episode_dir / "result.json"
    if not result_path.is_file():
        return None
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    transcript = episode_dir / "transcript.jsonl"
    events = list(iter_events(transcript))
    issued = issued_content(events)
    issued_text = "\n".join(issued)
    commands = issued_commands(events)
    duplicates = sum(count - 1 for count in Counter(commands).values() if count > 1)
    try:
        raw_text = transcript.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raw_text = ""
    tokens_in, tokens_out, estimated = extract_tokens(events, transcript)
    subgoals = result.get("subgoals") or []
    return {
        "schema": SCHEMA,
        "run_id": result.get("run_id"),
        "episode_id": result.get("episode_id"),
        "scenario": result.get("scenario"),
        "agent": result.get("agent"),
        "model": result.get("model"),
        "terminal_harness": result.get("terminal_harness", "pmx-cli"),
        "pass": result.get("pass"),
        "outcome": result.get("outcome"),
        "score": result.get("score", 1.0 if result.get("pass") else 0.0),
        "subgoals_total": len(subgoals),
        "subgoals_passed": sum(1 for goal in subgoals if goal.get("pass")),
        "failure_class": result.get("failure_class"),
        "wall_time_seconds": result.get("wall_time_seconds"),
        "timed_out": result.get("timed_out"),
        "pairmux_calls": result.get("steps"),
        "tool_calls": len(commands),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_estimated": estimated,
        "sleep_calls": len(SLEEP_RE.findall(issued_text)),
        "capture_pane_calls": len(CAPTURE_RE.findall(issued_text)),
        "send_keys_calls": len(SEND_KEYS_RE.findall(issued_text)),
        "pairmux_stub_hits": len(STUB_RE.findall(raw_text)),
        "duplicate_commands": duplicates,
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def write_markdown(path: Path, rows: list[dict]) -> None:
    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    for row in rows:
        key = (
            str(row["scenario"]),
            str(row["terminal_harness"]),
            str(row["agent"]),
            str(row["model"]),
        )
        groups.setdefault(key, []).append(row)
    lines = [
        "# eval metrics",
        "",
        "| scenario | harness | agent | model | n | mean score | mean wall (s) | mean tool calls | mean tokens out | sleeps | dup cmds | stub hits |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key in sorted(groups):
        items = groups[key]
        estimated = any(item["tokens_estimated"] for item in items)
        token_note = "~" if estimated else ""
        lines.append(
            "| {} | {} | {} | {} | {} | {:.2f} | {:.1f} | {:.1f} | {}{:.0f} | {} | {} | {} |".format(
                *key,
                len(items),
                mean([float(item["score"] or 0.0) for item in items]),
                mean([float(item["wall_time_seconds"] or 0.0) for item in items]),
                mean([float(item["tool_calls"]) for item in items]),
                token_note,
                mean([float(item["tokens_out"]) for item in items]),
                sum(item["sleep_calls"] for item in items),
                sum(item["duplicate_commands"] for item in items),
                sum(item["pairmux_stub_hits"] for item in items),
            )
        )
    lines += [
        "",
        "`~` marks token counts estimated from transcript size (the agent CLI reported no usage).",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in {"-h", "--help"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    rows: list[dict] = []
    for root_arg in argv[1:]:
        run_root = Path(root_arg)
        episodes = run_root / "episodes"
        if not episodes.is_dir():
            print(f"skipping {run_root}: no episodes/ directory", file=sys.stderr)
            continue
        run_rows: list[dict] = []
        for episode_dir in sorted(episodes.iterdir()):
            if not episode_dir.is_dir():
                continue
            row = episode_metrics(episode_dir)
            if row is not None:
                run_rows.append(row)
        if not run_rows:
            print(f"skipping {run_root}: no readable episodes", file=sys.stderr)
            continue
        out_jsonl = run_root / "metrics.jsonl"
        with out_jsonl.open("w", encoding="utf-8") as handle:
            for row in run_rows:
                handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")
        write_markdown(run_root / "metrics.md", run_rows)
        print(f"{run_root}: {len(run_rows)} episode(s) -> metrics.jsonl, metrics.md")
        rows.extend(run_rows)
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
