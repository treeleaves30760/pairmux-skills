#!/usr/bin/env python3
"""Repeatable, isolated cross-agent runner for the pairmux skill evals."""

from __future__ import annotations

import argparse
from array import array
import copy
import datetime as dt
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from collections.abc import Callable


EVALS_DIR = Path(__file__).resolve().parent
SCENARIOS_DIR = EVALS_DIR / "scenarios"
PROXY_SOURCE = EVALS_DIR / "pairmux_proxy.py"
SKILL_SOURCE = EVALS_DIR.parent / "skills" / "pairmux"
RESULT_SCHEMA = "pairmux.eval.episode.v1"
SUMMARY_SCHEMA = "pairmux.eval.summary.v1"
CALL_SCHEMA = "pairmux.eval.call.v1"
BROKER_REQUEST_SCHEMA = "pairmux.eval.exec.v1"
BROKER_RESPONSE_SCHEMA = "pairmux.eval.exec-result.v1"
BROKER_REJECTION_SCHEMA = "pairmux.eval.rejection.v1"
BROKER_MAX_FRAME_BYTES = 32 * 1024
SKILL_DISCOVERY_PATHS = {
    "opencode": Path(".config/opencode/skills/pairmux"),
    "claude": Path(".claude/skills/pairmux"),
    # Codex discovers shared skills from .agents/skills before legacy user roots.
    "codex": Path(".agents/skills/pairmux"),
}
GENERATED_NAMES = {
    "bad-transcript.txt",
    "check.out",
    "env.sh",
    "haystack.log",
    "port.txt",
    "token.txt",
}


@dataclass
class ProcessResult:
    returncode: int | None
    timed_out: bool
    duration_seconds: float
    start_error: str | None = None
    termination_signal: int | None = None
    timeout_inflight_call_ids: tuple[str, ...] = ()


@dataclass
class TraceResult:
    calls: list[dict[str, object]]
    errors: list[str]
    rejections: list[dict[str, object]]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def non_empty_text(value: str) -> str:
    parsed = value.strip()
    if not parsed:
        raise argparse.ArgumentTypeError("must not be empty")
    return parsed


def discover_scenarios() -> dict[int, str]:
    found: dict[int, str] = {}
    for path in SCENARIOS_DIR.glob("S[0-9]*"):
        match = re.fullmatch(r"S(\d+)", path.name)
        if not path.is_dir() or not match:
            continue
        required = (path / "TASK.md", path / "setup.sh", path / "check.sh")
        if all(item.is_file() for item in required):
            found[int(match.group(1))] = path.name
    return found


def parse_scenarios(selectors: list[str] | None, available: dict[int, str]) -> list[str]:
    if not available:
        raise ValueError(f"no scenarios found under {SCENARIOS_DIR}")
    if not selectors:
        return [available[number] for number in sorted(available)]

    selected: list[int] = []
    for selector in selectors:
        for raw_part in selector.split(","):
            part = raw_part.strip().upper()
            match = re.fullmatch(r"S?(\d+)(?:\s*-\s*S?(\d+))?", part)
            if not match:
                raise ValueError(f"invalid scenario selector: {raw_part!r}")
            first = int(match.group(1))
            last = int(match.group(2) or first)
            if last < first:
                raise ValueError(f"scenario range must be ascending: {raw_part!r}")
            selected.extend(range(first, last + 1))

    missing = sorted({number for number in selected if number not in available})
    if missing:
        rendered = ", ".join(f"S{number:02d}" for number in missing)
        raise ValueError(f"unknown scenario(s): {rendered}")

    ordered: list[str] = []
    seen: set[int] = set()
    for number in selected:
        if number not in seen:
            ordered.append(available[number])
            seen.add(number)
    return ordered


def build_agent_argv(
    agent: str,
    executable: str,
    task: str,
    model: str | None,
    codex_sandbox: str,
    working_directory: Path | None = None,
) -> list[str]:
    if agent == "opencode":
        argv = [executable, "--pure", "--auto"]
        if model:
            argv.extend(["--model", model])
        argv.extend(["run", "--format", "json"])
        if working_directory is not None:
            argv.extend(["--dir", str(working_directory.resolve())])
        argv.append(task)
        return argv
    if agent == "claude":
        argv = [
            executable,
            "-p",
            "--allowedTools",
            "Bash",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--setting-sources",
            "project",
            "--strict-mcp-config",
        ]
        if model:
            argv.extend(["--model", model])
        argv.append(task)
        return argv
    if agent == "codex":
        argv = [
            executable,
            "exec",
            "--sandbox",
            codex_sandbox,
            "--ephemeral",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--json",
            "--config",
            "shell_environment_policy.inherit=all",
        ]
        if model:
            argv.extend(["--model", model])
        argv.append(task)
        return argv
    raise ValueError(f"unsupported agent: {agent}")


def process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def parent_process_id(process_id: int) -> int | None:
    """Read a live process's parent without trusting agent-provided evidence."""
    if process_id <= 1:
        return None
    if sys.platform.startswith("linux"):
        try:
            stat = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8")
            fields = stat[stat.rfind(")") + 2 :].split()
            return int(fields[1])
        except (FileNotFoundError, IndexError, OSError, ValueError):
            return None

    ps = "/bin/ps" if Path("/bin/ps").is_file() else shutil.which("ps")
    if not ps:
        return None
    try:
        completed = subprocess.run(
            [ps, "-o", "ppid=", "-p", str(process_id)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1,
        )
        return int(completed.stdout.strip()) if completed.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def process_descends_from(process_id: int, ancestor_id: int, max_depth: int = 128) -> bool:
    """Return whether a live process is in the runner-observed agent ancestry."""
    current = process_id
    seen: set[int] = set()
    for _depth in range(max_depth):
        if current == ancestor_id:
            return True
        if current <= 1 or current in seen:
            return False
        seen.add(current)
        parent = parent_process_id(current)
        if parent is None:
            return False
        current = parent
    return False


def terminate_process_group(
    process: subprocess.Popen[bytes], grace_seconds: float = 2.0
) -> int | None:
    if os.name == "posix":
        if not process_group_exists(process.pid):
            return None
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return None
    else:
        if process.poll() is not None:
            return None
        process.terminate()
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            process.wait(timeout=min(0.05, max(0.001, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            pass
        if os.name == "posix":
            if not process_group_exists(process.pid):
                return signal.SIGTERM
        elif process.poll() is not None:
            return signal.SIGTERM
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return signal.SIGTERM
    else:
        process.kill()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    return signal.SIGKILL


def run_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path | None,
    timeout: float,
    merge_stderr: bool = False,
    cleanup_group: bool = False,
    pass_fds: tuple[int, ...] = (),
    timeout_observer: Callable[[subprocess.Popen[bytes]], tuple[str, ...]] | None = None,
) -> ProcessResult:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with stdout_path.open("wb") as stdout_stream:
        stderr_stream = None
        if not merge_stderr and stderr_path is not None:
            stderr_stream = stderr_path.open("wb")
        try:
            try:
                process = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_stream,
                    stderr=subprocess.STDOUT if merge_stderr else stderr_stream,
                    start_new_session=(os.name == "posix"),
                    pass_fds=pass_fds,
                )
            except OSError as error:
                message = f"{type(error).__name__}: {error}"
                if stderr_stream is not None:
                    stderr_stream.write((message + "\n").encode())
                return ProcessResult(None, False, round(time.monotonic() - started, 6), message)
            try:
                returncode = process.wait(timeout=timeout)
                cleanup_signal = terminate_process_group(process) if cleanup_group else None
                return ProcessResult(
                    returncode,
                    False,
                    round(time.monotonic() - started, 6),
                    termination_signal=cleanup_signal,
                )
            except subprocess.TimeoutExpired:
                inflight = timeout_observer(process) if timeout_observer else ()
                termination_signal = terminate_process_group(process)
                return ProcessResult(
                    process.poll(),
                    True,
                    round(time.monotonic() - started, 6),
                    termination_signal=termination_signal,
                    timeout_inflight_call_ids=tuple(inflight),
                )
        finally:
            if stderr_stream is not None:
                stderr_stream.close()


def probe_version(executable: str) -> str:
    process = subprocess.Popen(
        [executable, "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=(os.name == "posix"),
    )
    try:
        output, _ = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        terminate_process_group(process)
        return "unknown (version probe timed out)"
    text = output.decode(errors="replace").strip()
    first_line = text.splitlines()[0] if text else "unknown"
    if process.returncode != 0:
        return f"unknown (version probe exit {process.returncode}: {first_line})"
    return first_line


def resolve_pairmux(explicit: Path | None = None) -> str | None:
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise ValueError(f"--pairmux-bin is not executable: {candidate}")
        return str(candidate)
    repository = EVALS_DIR.parent
    for candidate in (
        repository.parent / "pairmux" / "bin" / "pairmux",
        repository.parent.parent / "pairmux" / "bin" / "pairmux",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    configured = os.environ.get("PAIRMUX_REAL_BIN")
    if configured and os.access(configured, os.X_OK):
        return str(Path(configured).expanduser().resolve())
    discovered = shutil.which("pairmux")
    if discovered:
        return str(Path(discovered).resolve())
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative_path = path.relative_to(root).as_posix().encode()
        digest.update(b"file\0")
        digest.update(relative_path)
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def git_provenance(root: Path = EVALS_DIR.parent) -> dict[str, object]:
    def git(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )

    revision = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=normal")
    return {
        "commit": revision.stdout.strip() if revision.returncode == 0 else None,
        "dirty": bool(status.stdout) if status.returncode == 0 else None,
    }


def completed_git_provenance(start: dict[str, object]) -> dict[str, object]:
    end = git_provenance()
    return {
        "commit": start.get("commit"),
        "dirty": start.get("dirty"),
        "end_commit": end.get("commit"),
        "end_dirty": end.get("dirty"),
        "stable": start == end,
    }


def scenario_source_hashes(scenario: str) -> dict[str, str]:
    root = SCENARIOS_DIR / scenario
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name not in GENERATED_NAMES
        and not path.name.startswith("transcript")
        and "__pycache__" not in path.parts
        and "state" not in path.parts
    }


def inferred_provider(model: str | None) -> str | None:
    if not model or "/" not in model:
        return None
    return model.split("/", 1)[0]


def verify_skill_discovery(
    *,
    agent: str,
    executable: str,
    agent_version: str,
    env: dict[str, str],
    cwd: Path,
    skill_dir: Path,
    host_home: Path,
    evidence_path: Path,
    model: str | None = None,
    claude_sentinel_token: str | None = None,
) -> dict[str, object]:
    expected = (skill_dir / "SKILL.md").resolve()
    if not expected.is_file() or sha256_file(expected) != sha256_file(SKILL_SOURCE / "SKILL.md"):
        raise RuntimeError("installed discovery skill is missing or has the wrong hash")
    if "mock-" in agent_version:
        evidence_path.write_text("mock discovery contract; path/hash checked by mock agent\n", encoding="utf-8")
        return {"verified": True, "method": "model-free-mock-contract", "path": str(expected)}
    if agent == "opencode":
        argv = [executable, "--pure", "debug", "skill"]
        method = "opencode-debug-skill"
    elif agent == "codex":
        argv = [executable, "debug", "prompt-input", "pairmux-eval-discovery"]
        method = "codex-debug-prompt-input"
    else:
        if not claude_sentinel_token:
            raise RuntimeError("Claude discovery sentinel was not installed")
        argv = [
            executable,
            "-p",
            "--setting-sources",
            "project",
            "--tools",
            "",
            "--output-format",
            "json",
            "--no-session-persistence",
        ]
        if model:
            argv.extend(["--model", model])
        argv.append("/pairmux-eval-sentinel")
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        evidence_path.write_text(completed.stdout, encoding="utf-8")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Claude discovery sentinel returned invalid JSON: {error}") from error
        result_text = payload.get("result") if isinstance(payload, dict) else None
        if completed.returncode != 0 or result_text != claude_sentinel_token:
            raise RuntimeError("Claude did not load the isolated project discovery sentinel")
        return {"verified": True, "method": "claude-project-sentinel", "path": str(expected)}
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=20,
    )
    evidence_path.write_text(completed.stdout, encoding="utf-8")
    expected_text = str(expected)
    if completed.returncode != 0 or expected_text not in completed.stdout:
        raise RuntimeError(f"{method} did not report the isolated skill path")
    host_prefix = str(host_home.expanduser().resolve()) + os.sep
    isolated_prefix = str(Path(env["HOME"]).resolve()) + os.sep
    absolute_skills = re.findall(r"(?:file:\s*)?(/[^\s\"'<>]+/SKILL\.md)", completed.stdout)
    leaked = [
        path
        for path in absolute_skills
        if os.path.realpath(path).startswith(host_prefix)
        and not os.path.realpath(path).startswith(isolated_prefix)
    ]
    if leaked:
        raise RuntimeError(f"{method} reported host skill paths: {leaked}")
    return {"verified": True, "method": method, "path": str(expected)}


def pairmux_state_namespace(state_root: Path, socket_name: str, tmux_tmpdir: str) -> Path:
    root = os.path.normpath(os.path.abspath(tmux_tmpdir or "/tmp"))
    if os.path.exists(root):
        root = os.path.realpath(root)
    socket_name = socket_name or "pairmux"
    identity = os.path.join(root, f"tmux-{os.getuid()}", socket_name)
    endpoint_hash = hashlib.sha256(identity.encode()).hexdigest()
    return state_root / ".sockets" / endpoint_hash


def install_isolated_skill(
    agent: str, isolated_home: Path, project_root: Path | None = None
) -> tuple[Path, str, str]:
    if not SKILL_SOURCE.is_dir():
        raise FileNotFoundError(f"canonical pairmux skill is missing: {SKILL_SOURCE}")
    source_tree_hash = sha256_tree(SKILL_SOURCE)
    source_skill_hash = sha256_file(SKILL_SOURCE / "SKILL.md")
    if agent == "claude" and project_root is not None:
        destination = project_root / ".claude/skills/pairmux"
    else:
        destination = isolated_home / SKILL_DISCOVERY_PATHS[agent]
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SKILL_SOURCE, destination)
    if sha256_tree(destination) != source_tree_hash:
        raise RuntimeError(f"isolated skill copy hash mismatch: {destination}")
    return destination, source_tree_hash, source_skill_hash


def isolated_agent_env(
    source: dict[str, str],
    *,
    agent: str,
    isolated_home: Path,
) -> dict[str, str]:
    """Build an agent environment without inheriting host HOME/config state."""
    exact = {
        "PATH",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "COLORTERM",
        "NO_COLOR",
        "SSH_AUTH_SOCK",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    }
    clean = {
        name: value
        for name, value in source.items()
        if name in exact or name.startswith("PAIRMUX_MOCK_")
    }
    clean["HOME"] = str(isolated_home)
    clean["XDG_CONFIG_HOME"] = str(isolated_home / ".config")
    clean["XDG_CACHE_HOME"] = str(isolated_home / ".cache")
    clean["XDG_DATA_HOME"] = str(isolated_home / ".local/share")
    clean["XDG_STATE_HOME"] = str(isolated_home / ".local/state")
    clean["CODEX_HOME"] = str(isolated_home / ".codex")
    clean["CLAUDE_CONFIG_DIR"] = str(isolated_home / ".claude")
    # Keep the selected CLI's explicit config root aligned with HOME/XDG. Host
    # values for these names are intentionally never copied above.
    if agent == "opencode":
        clean["OPENCODE_CONFIG_DIR"] = str(isolated_home / ".config/opencode")
        clean["OPENCODE_DISABLE_EXTERNAL_SKILLS"] = "1"
        clean["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
    return clean


def prepare_agent_project_isolation(
    *, agent: str, scenario_dir: Path, env: dict[str, str]
) -> dict[str, object]:
    """Anchor OpenCode project discovery to the isolated scenario directory."""
    scenario_dir = scenario_dir.resolve()
    if agent != "opencode":
        return {
            "method": "process-working-directory",
            "path": str(scenario_dir),
            "commit": None,
        }
    if (scenario_dir / ".git").exists():
        raise RuntimeError("isolated OpenCode scenario unexpectedly contains .git")
    git = shutil.which("git", path=env.get("PATH"))
    if not git:
        raise RuntimeError("git is required to isolate the OpenCode project root")

    git_env = env.copy()
    git_env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "pairmux-eval",
            "GIT_AUTHOR_EMAIL": "pairmux-eval@invalid",
            "GIT_COMMITTER_NAME": "pairmux-eval",
            "GIT_COMMITTER_EMAIL": "pairmux-eval@invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        }
    )

    def run_git(*arguments: str) -> str:
        try:
            completed = subprocess.run(
                [git, *arguments],
                cwd=scenario_dir,
                env=git_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"cannot initialize isolated OpenCode project: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                f"cannot initialize isolated OpenCode project: {detail or completed.returncode}"
            )
        return completed.stdout.strip()

    template_dir = Path(env["HOME"]) / ".pairmux-eval-empty-git-template"
    template_dir.mkdir(parents=True, exist_ok=True)
    run_git(
        "-c",
        "init.defaultBranch=pairmux-eval",
        "-c",
        "core.hooksPath=/dev/null",
        "init",
        "--quiet",
        f"--template={template_dir}",
        ".",
    )
    run_git("add", "--all", "--force")
    run_git(
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "--quiet",
        "--no-gpg-sign",
        "--no-verify",
        "--allow-empty",
        "-m",
        "pairmux eval fixture",
    )
    project_root = Path(run_git("rev-parse", "--show-toplevel")).resolve()
    if project_root != scenario_dir:
        raise RuntimeError(
            f"isolated OpenCode project resolved to {project_root}, expected {scenario_dir}"
        )
    commit = run_git("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise RuntimeError("isolated OpenCode project returned an invalid commit id")
    status = run_git("status", "--porcelain", "--untracked-files=all")
    if status:
        raise RuntimeError(f"isolated OpenCode project is dirty after commit: {status}")
    return {
        "method": "nested-committed-git-root",
        "path": str(project_root),
        "commit": commit,
    }


def make_read_only_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_symlink():
            continue
        path.chmod(0o555 if path.is_dir() else (0o555 if os.access(path, os.X_OK) else 0o444))
    root.chmod(0o555)


def verify_hashes(expected: dict[Path, str]) -> None:
    for path, digest in expected.items():
        if not path.is_file() or sha256_file(path) != digest:
            raise RuntimeError(f"runner control file hash mismatch: {path}")


def copy_fixture_worktree(scenario: str, work_root: Path) -> Path:
    """Copy only agent-facing fixtures; runner scripts stay outside the worktree."""
    source = SCENARIOS_DIR / scenario
    destination = work_root / scenario
    destination.mkdir(parents=True)
    excluded = {"TASK.md", "setup.sh", "check.sh", "env.sh"}
    for path in source.iterdir():
        if path.name in excluded or path.name in GENERATED_NAMES or path.name.startswith("transcript"):
            continue
        if path.name in {"state", "__pycache__", ".p", ".ps", ".pairmux-state", ".pairmux-tmp"}:
            continue
        target = destination / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        elif path.is_file():
            shutil.copy2(path, target)
    return destination


def prepare_control_sources(scenario: str, control_root: Path) -> tuple[Path, dict[Path, str]]:
    source_dir = SCENARIOS_DIR / scenario
    destination = control_root / "evals" / "scenarios" / scenario
    destination.mkdir(parents=True)
    files = {
        EVALS_DIR / "lib.sh": control_root / "evals" / "lib.sh",
        source_dir / "setup.sh": destination / "setup.sh",
        source_dir / "check.sh": destination / "check.sh",
        source_dir / "TASK.md": destination / "TASK.md",
    }
    expected: dict[Path, str] = {}
    for source, target in files.items():
        shutil.copy2(source, target)
        expected[target] = sha256_file(source)
    return destination, expected


def install_shell_path_guard(runtime_root: Path, proxy_dir: Path) -> dict[str, str]:
    """Keep the proxy first even when an agent tool starts a login shell."""
    runtime_root.mkdir(parents=True, exist_ok=True)
    export = f"export PATH={shlex.quote(str(proxy_dir))}:\"$PATH\"\n"
    # Bash performs command substitution while expanding the BASH_ENV *path*.
    # Keep activation paths outside user-controlled output roots and restrict
    # their names to tempfile's safe alphabet. A copy remains in the artifact.
    (runtime_root / "shell-env.sh").write_text(export, encoding="utf-8")
    activation_root = Path(tempfile.mkdtemp(prefix="pairmux-eval-shell-", dir="/tmp"))
    activation_root.chmod(0o700)
    shell_init = activation_root / "shell-env.sh"
    shell_init.write_text(export, encoding="utf-8")
    zdotdir = activation_root / "zdotdir"
    zdotdir.mkdir(exist_ok=True)
    for name in (".zshenv", ".zprofile", ".zshrc", ".zlogin"):
        (zdotdir / name).write_text(export, encoding="utf-8")
    return {
        "BASH_ENV": str(shell_init),
        "ENV": str(shell_init),
        "ZDOTDIR": str(zdotdir),
    }


def copy_scenario(scenario: str, work_root: Path) -> Path:
    evals_copy = work_root / "evals"
    scenario_copy = evals_copy / "scenarios" / scenario
    evals_copy.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EVALS_DIR / "lib.sh", evals_copy / "lib.sh")

    def ignore(_directory: str, names: list[str]) -> set[str]:
        ignored = {name for name in names if name in GENERATED_NAMES or name.startswith("transcript")}
        ignored.update(name for name in names if name in {"state", "__pycache__"})
        ignored.update(
            name for name in names
            if name in {".p", ".ps", ".pairmux-state", ".pairmux-tmp"}
            or name.startswith("tmux-")
        )
        return ignored

    shutil.copytree(SCENARIOS_DIR / scenario, scenario_copy, ignore=ignore)
    return scenario_copy


@dataclass
class BrokerExecution:
    record: dict[str, object]
    process: subprocess.Popen[bytes]
    connection: socket.socket
    cancel: threading.Event
    done: threading.Event
    client_connected: bool = True
    cancel_reason: str | None = None


class BrokerPolicyRejection(Exception):
    """A safely denied request that never reached the fixed pairmux binary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        requested_cwd: str,
        resolved_cwd: Path,
        allowed_cwd: Path,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.requested_cwd = requested_cwd
        self.resolved_cwd = resolved_cwd
        self.allowed_cwd = allowed_cwd


class PairmuxBroker:
    """Runner-owned execution boundary and authoritative in-memory call ledger."""

    def __init__(
        self,
        socket_path: Path,
        *,
        real_pairmux: Path,
        real_pairmux_sha256: str,
        fixed_env: dict[str, str],
        allowed_cwd: Path,
        expected_socket: str,
        max_requests: int = 256,
    ) -> None:
        if os.name != "posix" or not hasattr(socket, "SCM_RIGHTS"):
            raise RuntimeError("pairmux eval broker requires Unix descriptor passing")
        self.socket_path = socket_path
        self.real_pairmux = real_pairmux.resolve()
        self.real_pairmux_sha256 = real_pairmux_sha256
        self.fixed_env = fixed_env.copy()
        self.allowed_cwd = allowed_cwd.resolve()
        self.expected_socket = expected_socket
        self.max_requests = max_requests
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._listener: socket.socket | None = None
        self._listener_thread: threading.Thread | None = None
        self._handler_threads: list[threading.Thread] = []
        self._active: dict[str, BrokerExecution] = {}
        self._request_count = 0
        self._calls: list[dict[str, object]] = []
        self._errors: list[str] = []
        self._rejections: list[dict[str, object]] = []
        self._final: TraceResult | None = None

    def start(self) -> None:
        if self._listener is not None:
            raise RuntimeError("pairmux eval broker already started")
        if self.socket_path.exists():
            raise RuntimeError(f"pairmux eval broker socket already exists: {self.socket_path}")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        listener.listen(32)
        listener.settimeout(0.1)
        self._listener = listener
        self._listener_thread = threading.Thread(
            target=self._accept_loop,
            name="pairmux-eval-broker",
            daemon=True,
        )
        self._listener_thread.start()

    def _error(self, message: str) -> None:
        with self._lock:
            self._errors.append(message)

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._closing.is_set():
            try:
                connection, _address = self._listener.accept()
            except socket.timeout:
                continue
            except OSError as error:
                if not self._closing.is_set():
                    self._error(f"broker accept failed: {error}")
                break
            handler = threading.Thread(
                target=self._handle_connection,
                args=(connection,),
                name="pairmux-eval-broker-call",
                daemon=True,
            )
            with self._lock:
                self._handler_threads.append(handler)
            handler.start()

    @staticmethod
    def _peer_credentials(connection: socket.socket) -> tuple[int, int]:
        if sys.platform.startswith("linux") and hasattr(socket, "SO_PEERCRED"):
            raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            peer_pid, peer_uid, _peer_gid = struct.unpack("=3i", raw)
            return peer_pid, peer_uid
        if sys.platform == "darwin":
            peer_pid = struct.unpack("=i", connection.getsockopt(0, 2, 4))[0]
            credentials = connection.getsockopt(0, 1, 8)
            _version, peer_uid = struct.unpack("=II", credentials)
            return peer_pid, peer_uid
        raise RuntimeError("kernel peer credentials are unsupported on this platform")

    @staticmethod
    def _json_without_duplicate_keys(encoded: bytes) -> object:
        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON field: {key}")
                result[key] = value
            return result

        return json.loads(encoded, object_pairs_hook=reject_duplicates)

    @staticmethod
    def _close_descriptors(descriptors: list[int]) -> None:
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass

    def _recv_request(
        self, connection: socket.socket
    ) -> tuple[dict[str, object], list[int]]:
        descriptor_array = array("i")
        ancillary_size = socket.CMSG_SPACE(3 * descriptor_array.itemsize)
        connection.settimeout(5.0)
        data, ancillary, flags, _address = connection.recvmsg(
            BROKER_MAX_FRAME_BYTES + 4,
            ancillary_size,
        )
        if not data:
            raise ValueError("empty broker request")
        if flags & getattr(socket, "MSG_CTRUNC", 0):
            raise ValueError("truncated broker descriptor message")
        for level, kind, value in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                usable = len(value) - len(value) % descriptor_array.itemsize
                descriptor_array.frombytes(value[:usable])
        descriptors = descriptor_array.tolist()
        try:
            while len(data) < 4:
                chunk = connection.recv(4 - len(data))
                if not chunk:
                    raise ValueError("truncated broker request header")
                data += chunk
            payload_length = struct.unpack("!I", data[:4])[0]
            if payload_length > BROKER_MAX_FRAME_BYTES:
                raise ValueError("broker request exceeds 32 KiB")
            frame_length = 4 + payload_length
            while len(data) < frame_length:
                chunk = connection.recv(frame_length - len(data))
                if not chunk:
                    raise ValueError("truncated broker request payload")
                data += chunk
            if len(data) != frame_length:
                raise ValueError("broker request contains trailing bytes")
            payload = self._json_without_duplicate_keys(data[4:])
            if (
                not isinstance(payload, dict)
                or set(payload) != {"schema", "argv", "cwd"}
                or payload.get("schema") != BROKER_REQUEST_SCHEMA
                or not isinstance(payload.get("argv"), list)
                or not all(isinstance(value, str) for value in payload["argv"])
                or not isinstance(payload.get("cwd"), str)
            ):
                raise ValueError("broker request does not match the exact execution schema")
            if any("\0" in value for value in [*payload["argv"], payload["cwd"]]):
                raise ValueError("broker request contains a NUL byte")
            if len(descriptors) != 3:
                raise ValueError("broker request must pass stdin, stdout, and stderr")
            connection.settimeout(None)
            return payload, descriptors
        except Exception:
            self._close_descriptors(descriptors)
            raise

    def _validated_cwd(self, requested: str) -> Path:
        path = Path(requested)
        if not path.is_absolute():
            raise ValueError("broker cwd must be absolute")
        resolved = path.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("broker cwd is not a directory")
        if os.path.commonpath((str(self.allowed_cwd), str(resolved))) != str(self.allowed_cwd):
            raise BrokerPolicyRejection(
                "cwd-outside-work-root",
                "broker cwd escapes the episode work root",
                requested_cwd=requested,
                resolved_cwd=resolved,
                allowed_cwd=self.allowed_cwd,
            )
        return resolved

    def _validate_socket_override(self, argv: list[str]) -> None:
        index = 0
        while index < len(argv):
            value = argv[index]
            if value == "--json":
                index += 1
                continue
            if value == "--socket":
                if index + 1 >= len(argv) or argv[index + 1] != self.expected_socket:
                    raise ValueError("broker request overrides the episode pairmux socket")
                index += 2
                continue
            if value.startswith("--socket="):
                if value.split("=", 1)[1] != self.expected_socket:
                    raise ValueError("broker request overrides the episode pairmux socket")
                index += 1
                continue
            break

    @staticmethod
    def _send_result(
        connection: socket.socket, returncode: int, error: str | None = None
    ) -> None:
        encoded = json.dumps(
            {
                "schema": BROKER_RESPONSE_SCHEMA,
                "returncode": returncode,
                "error": error,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        connection.sendall(struct.pack("!I", len(encoded)) + encoded)

    def _monitor_client(self, execution: BrokerExecution) -> None:
        try:
            unexpected = execution.connection.recv(1)
        except OSError:
            unexpected = b""
        if execution.done.is_set():
            return
        with self._lock:
            execution.client_connected = False
            execution.record["client_connected_at_finish"] = False
            execution.cancel_reason = (
                "unexpected-client-data" if unexpected else "client-disconnected"
            )
            execution.record["cancel_reason"] = execution.cancel_reason
            if unexpected:
                self._errors.append(
                    f"broker protocol error for {execution.record['id']}: "
                    "client sent data after its execution request"
                )
        execution.cancel.set()

    @staticmethod
    def _signal_child(process: subprocess.Popen[bytes], signum: int) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    def _finish_record(
        self,
        record: dict[str, object],
        *,
        returncode: int,
        started_monotonic: float,
    ) -> None:
        record.update(
            {
                "finished_at": utc_now(),
                "duration_seconds": round(time.monotonic() - started_monotonic, 6),
                "exit_code": returncode,
            }
        )

    def _handle_connection(self, connection: socket.socket) -> None:
        descriptors: list[int] = []
        execution: BrokerExecution | None = None
        peer_pid: int | None = None
        peer_uid: int | None = None
        request: dict[str, object] | None = None
        try:
            peer_pid, peer_uid = self._peer_credentials(connection)
            if peer_uid != os.geteuid():
                raise ValueError(f"broker peer uid {peer_uid} does not match runner uid")
            request, descriptors = self._recv_request(connection)
            with self._lock:
                if self._request_count >= self.max_requests:
                    raise ValueError("broker request limit exceeded")
                self._request_count += 1
            argv = list(request["argv"])
            self._validate_socket_override(argv)
            if sha256_file(self.real_pairmux) != self.real_pairmux_sha256:
                raise RuntimeError("broker real pairmux hash changed before execution")
            try:
                client_process_group = os.getpgid(peer_pid)
            except (ProcessLookupError, PermissionError):
                raise ValueError("broker peer process is not live") from None
            cwd = self._validated_cwd(str(request["cwd"]))

            started_at = utc_now()
            started_ns = time.time_ns()
            started_monotonic = time.monotonic()
            call_id = uuid.uuid4().hex
            record: dict[str, object] = {
                "schema": CALL_SCHEMA,
                "id": call_id,
                "argv": argv,
                "cwd": str(cwd),
                "pid": None,
                "ppid": os.getpid(),
                "process_group": None,
                "client_pid": peer_pid,
                "client_uid": peer_uid,
                "client_process_group": client_process_group,
                "client_connected_at_finish": True,
                "pairmux_socket": self.expected_socket,
                "pairmux_state_dir": self.fixed_env.get("PAIRMUX_STATE_DIR", ""),
                "started_at": started_at,
                "started_at_unix_ns": started_ns,
                "finished_at": None,
                "duration_seconds": None,
                "exit_code": None,
            }
            with self._lock:
                self._calls.append(record)
            try:
                process = subprocess.Popen(
                    [str(self.real_pairmux), *argv],
                    cwd=cwd,
                    env=self.fixed_env,
                    stdin=descriptors[0],
                    stdout=descriptors[1],
                    stderr=descriptors[2],
                    start_new_session=True,
                )
            except (OSError, ValueError) as error:
                message = f"cannot execute fixed real pairmux: {error}"
                with self._lock:
                    self._finish_record(
                        record,
                        returncode=127,
                        started_monotonic=started_monotonic,
                    )
                    record["start_error"] = message
                    self._errors.append(f"broker execution error for {call_id}: {message}")
                self._send_result(connection, 127, message)
                return
            finally:
                self._close_descriptors(descriptors)
                descriptors = []

            record["pid"] = process.pid
            record["process_group"] = process.pid
            execution = BrokerExecution(
                record=record,
                process=process,
                connection=connection,
                cancel=threading.Event(),
                done=threading.Event(),
            )
            with self._lock:
                self._active[call_id] = execution
            monitor = threading.Thread(
                target=self._monitor_client,
                args=(execution,),
                name="pairmux-eval-broker-client",
                daemon=True,
            )
            monitor.start()

            termination_sent: int | None = None
            termination_deadline: float | None = None
            while process.poll() is None:
                if execution.cancel.wait(0.05):
                    if termination_sent is None:
                        termination_sent = signal.SIGTERM
                        termination_deadline = time.monotonic() + 1.0
                        self._signal_child(process, signal.SIGTERM)
                    elif termination_deadline and time.monotonic() >= termination_deadline:
                        termination_sent = signal.SIGKILL
                        termination_deadline = None
                        self._signal_child(process, signal.SIGKILL)
            returncode = process.wait()
            execution.done.set()
            with self._lock:
                self._active.pop(call_id, None)
                self._finish_record(
                    record,
                    returncode=returncode,
                    started_monotonic=started_monotonic,
                )
                if termination_sent is not None:
                    record["received_signals"] = [termination_sent]
                    record["exit_signal"] = -returncode if returncode < 0 else None
            try:
                self._send_result(connection, returncode)
            except OSError:
                pass
            monitor.join(1.0)
        except BrokerPolicyRejection as error:
            rejection = {
                "schema": BROKER_REJECTION_SCHEMA,
                "code": error.code,
                "message": str(error),
                "requested_cwd": error.requested_cwd,
                "resolved_cwd": str(error.resolved_cwd),
                "allowed_cwd": str(error.allowed_cwd),
                "argv": list(request["argv"]) if request is not None else [],
                "executed": False,
                "client_pid": peer_pid,
                "client_uid": peer_uid,
                "observed_at": utc_now(),
                "observed_at_unix_ns": time.time_ns(),
            }
            with self._lock:
                self._rejections.append(rejection)
            try:
                self._send_result(connection, 125, str(error))
            except OSError:
                pass
        except (json.JSONDecodeError, OSError, RuntimeError, ValueError) as error:
            self._error(f"broker protocol error: {error}")
            try:
                self._send_result(connection, 125, str(error))
            except OSError:
                pass
        finally:
            self._close_descriptors(descriptors)
            if execution is not None:
                execution.done.set()
                with self._lock:
                    self._active.pop(str(execution.record["id"]), None)
            connection.close()

    def inflight_at_timeout(self, process: subprocess.Popen[bytes]) -> tuple[str, ...]:
        observed_at = utc_now()
        inflight: list[str] = []
        with self._lock:
            for call_id, execution in self._active.items():
                child_live = execution.process.poll() is None
                try:
                    client_group = os.getpgid(int(execution.record["client_pid"]))
                    client_live = True
                except (ProcessLookupError, PermissionError):
                    client_group = None
                    client_live = False
                client_group_matches = client_group == process.pid
                client_ancestry_matches = client_live and process_descends_from(
                    int(execution.record["client_pid"]), process.pid
                )
                execution.record.update(
                    {
                        "runner_timeout_observed_at": observed_at,
                        "runner_timeout_pid_live": child_live,
                        "runner_timeout_client_live": client_live
                        and execution.client_connected,
                        "runner_timeout_client_pgid_match": client_group_matches,
                        "runner_timeout_client_ancestry_match": client_ancestry_matches,
                    }
                )
                if (
                    child_live
                    and client_live
                    and execution.client_connected
                    and client_ancestry_matches
                ):
                    execution.record["runner_timeout_interrupted"] = True
                    inflight.append(call_id)
        return tuple(sorted(inflight))

    def stop_and_finalize(self, timeout: float = 5.0) -> TraceResult:
        if self._final is not None:
            return self._final
        self._closing.set()
        if self._listener is not None:
            self._listener.close()
        with self._lock:
            active = list(self._active.values())
            for execution in active:
                if execution.cancel_reason is None:
                    execution.cancel_reason = "broker-finalize"
                    execution.record["cancel_reason"] = execution.cancel_reason
                execution.cancel.set()
        if self._listener_thread is not None:
            self._listener_thread.join(timeout)
        deadline = time.monotonic() + timeout
        with self._lock:
            handlers = list(self._handler_threads)
        for handler in handlers:
            handler.join(max(0.0, deadline - time.monotonic()))
        live_handlers = [handler.name for handler in handlers if handler.is_alive()]
        if live_handlers:
            self._error(f"broker handlers did not stop: {live_handlers}")
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        with self._lock:
            calls = copy.deepcopy(self._calls)
            errors = list(self._errors)
            rejections = copy.deepcopy(self._rejections)
        calls.sort(key=lambda item: (int(item["started_at_unix_ns"]), str(item["id"])))
        rejections.sort(
            key=lambda item: (int(item["observed_at_unix_ns"]), str(item["code"]))
        )
        for call in calls:
            if call.get("exit_code") is None:
                errors.append(f"broker call was not reaped: {call['id']}")
        self._final = TraceResult(calls=calls, errors=errors, rejections=rejections)
        return self._final


def write_broker_calls(destination: Path, calls: list[dict[str, object]]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as stream:
        for record in calls:
            json.dump(record, stream, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            stream.write("\n")


def write_broker_rejections(
    destination: Path, rejections: list[dict[str, object]]
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as stream:
        for record in rejections:
            json.dump(record, stream, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            stream.write("\n")


def effective_pairmux_command(argv: object) -> tuple[str, list[str]] | None:
    """Return the subcommand and its argv after removing pairmux global flags."""
    if not isinstance(argv, list) or not all(isinstance(value, str) for value in argv):
        return None
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--json":
            index += 1
            continue
        if value == "--socket":
            index += 2
            continue
        if value.startswith("--socket=") or value == "--":
            index += 1
            continue
        return value, argv[index + 1 :]
    return None


def call_was_interrupted(call: dict[str, object]) -> bool:
    return bool(
        call.get("runner_timeout_interrupted") is True
        and call.get("runner_timeout_pid_live") is True
        and call.get("runner_timeout_client_live") is True
        and call.get("runner_timeout_client_ancestry_match") is True
    )


def argument_value(arguments: list[str], name: str) -> str | None:
    for index, value in enumerate(arguments):
        if value == name and index + 1 < len(arguments):
            return arguments[index + 1]
        if value.startswith(name + "="):
            return value.split("=", 1)[1]
    return None


def positional_arguments(arguments: list[str], value_flags: set[str]) -> list[str]:
    positional: list[str] = []
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value == "--":
            positional.extend(arguments[index + 1 :])
            break
        if value in value_flags:
            index += 2
            continue
        if any(value.startswith(flag + "=") for flag in value_flags) or value.startswith("-"):
            index += 1
            continue
        positional.append(value)
        index += 1
    return positional


def command_terminal(arguments: list[str]) -> str | None:
    values = positional_arguments(
        arguments,
        {"--timeout", "--idle", "--pattern", "--head", "--tail", "--text", "--key", "--cmd", "--grep", "--range"},
    )
    return values[0] if values else None


def calls_have_human_wait(
    calls: list[dict[str, object]], *, require_interrupted: bool = False
) -> bool:
    for call in calls:
        command = effective_pairmux_command(call.get("argv"))
        if command is None:
            continue
        subcommand, arguments = command
        if (
            subcommand == "wait"
            and "--human" in arguments
            and "--notify" in arguments
            and argument_value(arguments, "--timeout") is None
            and (not require_interrupted or call_was_interrupted(call))
        ):
            return True
    return False


def s05_handoff_call(calls: list[dict[str, object]]) -> dict[str, object] | None:
    prompt_terminals: set[str] = set()
    for call in calls:
        command = effective_pairmux_command(call.get("argv"))
        if command is None:
            continue
        subcommand, arguments = command
        terminal = command_terminal(arguments)
        if (
            subcommand == "run"
            and call.get("exit_code") == 0
            and terminal
            and any("secret.sh" in value for value in arguments)
        ):
            prompt_terminals.add(terminal)
        if (
            subcommand == "wait"
            and terminal in prompt_terminals
            and "--human" in arguments
            and "--notify" in arguments
            and argument_value(arguments, "--timeout") is None
            and call_was_interrupted(call)
        ):
            return call
    return None


def decoded_calls(calls: list[dict[str, object]]) -> list[tuple[int, dict[str, object], str, list[str]]]:
    decoded: list[tuple[int, dict[str, object], str, list[str]]] = []
    for index, call in enumerate(calls):
        command = effective_pairmux_command(call.get("argv"))
        if command is not None:
            decoded.append((index, call, command[0], command[1]))
    return decoded


def validate_scenario_calls(scenario: str, calls: list[dict[str, object]]) -> list[str]:
    """Prove task behavior from exact proxy calls, not agent-writable marker files alone."""
    decoded = decoded_calls(calls)
    errors: list[str] = []

    def matching(command: str, needle: str = "") -> list[tuple[int, dict[str, object], list[str]]]:
        return [
            (index, call, arguments)
            for index, call, name, arguments in decoded
            if name == command
            and call.get("exit_code") == 0
            and (not needle or any(needle in value for value in arguments))
        ]

    def program_launches(needle: str) -> list[tuple[int, str, str]]:
        launches: list[tuple[int, str, str]] = []
        for index, call, name, arguments in decoded:
            if call.get("exit_code") != 0:
                continue
            terminal: str | None = None
            program = ""
            if name == "new":
                terminal = argument_value(arguments, "--name")
                program = argument_value(arguments, "--cmd") or ""
            elif name == "run":
                values = positional_arguments(
                    arguments,
                    {
                        "--timeout",
                        "--idle",
                        "--pattern",
                        "--head",
                        "--tail",
                        "--text",
                        "--key",
                        "--cmd",
                        "--grep",
                        "--range",
                    },
                )
                if len(values) >= 2:
                    terminal, program = values[0], values[1]
            if terminal and needle in program:
                launches.append((index, terminal, program))
        return launches

    if scenario == "S01":
        runs = [item for item in matching("run", "PAIRMUX-S01-OK") if item[1].get("exit_code") == 0]
        if not runs:
            errors.append("no successful proxied run produced PAIRMUX-S01-OK")
    elif scenario == "S02":
        runs = [item for item in matching("run", "slow-build.sh") if item[1].get("exit_code") == 0]
        if not runs:
            errors.append("no successful proxied run executed slow-build.sh")
    elif scenario == "S03":
        displays = matching("run", "haystack.log")
        proved = False
        for display_index, _call, display_args in displays:
            terminal = command_terminal(display_args)
            for log_index, _log_call, log_args in matching("log"):
                grep_value = argument_value(log_args, "--grep") or ""
                if (
                    terminal
                    and command_terminal(log_args) == terminal
                    and log_index > display_index
                    and re.search(r"FATAL|E4231", grep_value, re.IGNORECASE)
                ):
                    proved = True
        if not proved:
            errors.append("missing later proxied log --grep on the terminal that displayed haystack.log")
    elif scenario == "S04":
        prompts = matching("run", "confirm.sh")
        answers = matching("send")
        proved = False
        for prompt_index, _call, prompt_args in prompts:
            terminal = command_terminal(prompt_args)
            terminal_answers = [
                args
                for index, _answer, args in answers
                if index > prompt_index and command_terminal(args) == terminal
            ]
            yes_answers = [
                args
                for args in terminal_answers
                if (argument_value(args, "--text") or "").strip().lower() in {"y", "yes"}
            ]
            if len(terminal_answers) == 1 and len(yes_answers) == 1 and "--enter" in yes_answers[0]:
                proved = True
        if not proved:
            errors.append("confirmation was not answered yes exactly once on its proxied terminal")
    elif scenario == "S05":
        if s05_handoff_call(calls) is None:
            errors.append("missing runner-timeout-interrupted wait --human --notify on prompt terminal")
    elif scenario == "S06":
        repls = [
            (index, terminal)
            for index, terminal, program in program_launches("python")
            if re.search(r"(^|[/\s])python3?(?:\s|$)", program)
        ]
        proved = False
        for start_index, terminal in repls:
            expression = False
            exited = False
            for index, _call, arguments in matching("send"):
                if index <= start_index or command_terminal(arguments) != terminal:
                    continue
                text_value = argument_value(arguments, "--text") or ""
                keys = [argument_value(arguments, "--key") or ""]
                expression = expression or "1234 * 5678" in text_value or "1234*5678" in text_value
                exited = exited or bool(re.search(r"\b(exit|quit)\s*\(\s*\)", text_value)) or any(
                    value.lower() in {"c-d", "ctrl-d"} for value in keys
                )
            proved = proved or (expression and exited)
        if not proved:
            errors.append("proxied REPL session did not both evaluate the expression and exit cleanly")
    elif scenario == "S07":
        escaped = any(
            command_terminal(arguments) == "report"
            and (
                (argument_value(arguments, "--text") or "") == "q"
                or (argument_value(arguments, "--key") or "").lower() == "q"
            )
            for _index, _call, arguments in matching("send")
        )
        if not escaped:
            errors.append("no proxied q was sent to the report pager")
    elif scenario == "S08":
        servers = program_launches("server.sh")
        clients = program_launches("hit.sh")
        proved = False
        for server_index, server_terminal, _server_program in servers:
            for client_index, client_terminal, _client_program in clients:
                if not server_terminal or not client_terminal or server_terminal == client_terminal:
                    continue
                for log_index, _log, log_args in matching("log"):
                    grep_value = argument_value(log_args, "--grep")
                    if (
                        command_terminal(log_args) == server_terminal
                        and server_index < client_index < log_index
                        and (
                            grep_value is None
                            or re.search(
                                r"GET|HTTP|(?<!\d)200(?!\d)",
                                grep_value,
                                re.IGNORECASE,
                            )
                        )
                    ):
                        proved = True
        if not proved:
            errors.append("server/client were not run in distinct terminals followed by server log grep")
    elif scenario == "S09":
        interrupted_at = [
            index
            for index, _call, arguments in matching("send")
            if command_terminal(arguments) == "worker"
            and (argument_value(arguments, "--key") or "").lower() in {"c-c", "ctrl-c"}
        ]
        recovered = [
            index
            for index, _call, arguments in matching("run", "WORKER-RECOVERED")
            if command_terminal(arguments) == "worker"
        ]
        if not any(first < second for first in interrupted_at for second in recovered):
            errors.append("worker was not interrupted before the proxied recovery run on the same terminal")
    elif scenario == "S10":
        if not any(
            name in {"peek", "log"} and command_terminal(arguments) == "handoff"
            for _index, call, name, arguments in decoded
            if call.get("exit_code") == 0
        ):
            errors.append("handoff note was not read through a proxied peek/log call")
    else:
        errors.append(f"no proxy-call validator for {scenario}")
    return errors


def atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=True, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, path)


def relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def cleanup_tmux(socket_name: str, env: dict[str, str], log_path: Path) -> None:
    tmux = shutil.which("tmux", path=env.get("PATH"))
    if not tmux:
        log_path.write_text("tmux not found; no server cleanup attempted\n", encoding="utf-8")
        return
    result = run_process(
        [tmux, "-L", socket_name, "kill-server"],
        cwd=log_path.parent,
        env=env,
        stdout_path=log_path,
        stderr_path=None,
        timeout=10,
        merge_stderr=True,
    )
    if result.timed_out:
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write("tmux cleanup timed out\n")


def failure_class(
    setup: ProcessResult,
    agent: ProcessResult | None,
    check: ProcessResult | None,
) -> str | None:
    if setup.start_error:
        return "setup_start_failed"
    if setup.timed_out:
        return "setup_timeout"
    if setup.returncode != 0:
        return "setup_failed"
    if agent is None or agent.start_error:
        return "agent_start_failed"
    if agent.timed_out:
        return "agent_timeout"
    if agent.returncode != 0:
        return "agent_failed"
    if check is None or check.start_error:
        return "check_start_failed"
    if check.timed_out:
        return "check_timeout"
    if check.returncode != 0:
        return "check_failed"
    return None


def run_episode(
    *,
    run_root: Path,
    run_id: str,
    scenario: str,
    repetition: int,
    agent: str,
    agent_executable: str,
    agent_version: str,
    model: str | None,
    provider: str | None,
    codex_sandbox: str,
    real_pairmux: str,
    pairmux_version: str,
    pairmux_sha256: str,
    git_start: dict[str, object],
    timeout: float,
) -> dict[str, object]:
    episode_started_at = utc_now()
    episode_started = time.monotonic()
    uniqueness = hashlib.sha256(f"{run_id}:{scenario}:{repetition}".encode()).hexdigest()[:12]
    episode_id = f"{scenario}-r{repetition:02d}-{uniqueness[:6]}"
    episode_root = run_root / "episodes" / episode_id
    work_root = episode_root / "work"
    artifact_root = episode_root / "runner-artifacts"
    episode_root.mkdir(parents=True)
    work_root.mkdir()
    artifact_root.mkdir()

    # Keep Unix socket paths below macOS's 104-byte sockaddr_un limit.
    control_root = Path(tempfile.mkdtemp(prefix="pairmux-eval-control-", dir="/tmp")).resolve()
    control_root.chmod(0o700)
    control_runtime = control_root / "runtime"
    evidence_dir = control_root / "evidence"
    proxy_dir = control_runtime / "bin"
    state_dir = control_runtime / "state"
    isolated_home = control_root / "home"
    for directory in (control_runtime, evidence_dir, proxy_dir, state_dir, isolated_home):
        directory.mkdir(parents=True, exist_ok=True)

    socket_name = f"pmx-eval-{uniqueness}"
    scenario_dir = copy_fixture_worktree(scenario, work_root)
    control_scenario, control_hashes = prepare_control_sources(scenario, control_root)
    skill_dir, skill_tree_sha256, skill_md_sha256 = install_isolated_skill(
        agent, isolated_home, work_root
    )
    claude_sentinel_token: str | None = None
    if agent == "claude":
        claude_sentinel_token = f"PAIRmux-discovery-{uuid.uuid4().hex}"
        sentinel_dir = work_root / ".claude/skills/pairmux-eval-sentinel"
        sentinel_dir.mkdir(parents=True)
        (sentinel_dir / "SKILL.md").write_text(
            "---\n"
            "name: pairmux-eval-sentinel\n"
            "description: Internal isolated eval discovery sentinel.\n"
            "---\n\n"
            f"When invoked, respond with exactly `{claude_sentinel_token}` and nothing else.\n",
            encoding="utf-8",
        )
        make_read_only_tree(sentinel_dir)
    skill_discovery_path = str(skill_dir)
    skill_artifact_dir = artifact_root / "skill"
    make_read_only_tree(skill_dir)
    make_read_only_tree(control_root / "evals")

    proxy_path = proxy_dir / "pairmux"
    shutil.copy2(PROXY_SOURCE, proxy_path)
    proxy_path.chmod(0o555)
    real_proxy_target = control_runtime / "real-pairmux"
    shutil.copy2(real_pairmux, real_proxy_target)
    real_proxy_target.chmod(0o555)
    proxy_dir.chmod(0o555)
    shell_path_guard = install_shell_path_guard(control_runtime / "shell", proxy_dir)
    task_path = control_scenario / "TASK.md"
    verify_hashes(control_hashes)
    task = task_path.read_text(encoding="utf-8")
    task_sha256 = hashlib.sha256(task.encode()).hexdigest()
    agent_argv = build_agent_argv(
        agent,
        agent_executable,
        task,
        model,
        codex_sandbox,
        working_directory=scenario_dir,
    )

    host_home = Path(os.environ.get("HOME", "~")).expanduser()
    clean_env = isolated_agent_env(os.environ.copy(), agent=agent, isolated_home=isolated_home)
    for variable in (
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "CODEX_HOME",
        "CLAUDE_CONFIG_DIR",
    ):
        Path(clean_env[variable]).mkdir(parents=True, exist_ok=True)
    tmux_tmpdir = clean_env.get("TMPDIR", "/tmp")
    state_namespace = pairmux_state_namespace(state_dir, socket_name, tmux_tmpdir)
    env_file = control_runtime / "env.sh"
    setup_env = clean_env.copy()
    setup_env.update(
        {
            "PAIRMUX_EVAL_RUN_ID": run_id,
            "PAIRMUX_EVAL_EPISODE_ID": episode_id,
            "PAIRMUX_EVAL_SOCKET": socket_name,
            "PAIRMUX_EVAL_STATE_DIR": str(state_dir),
            "PAIRMUX_EVAL_SCENARIO_DIR": str(scenario_dir),
            "PAIRMUX_EVAL_CONTROL_ROOT": str(control_root),
            "PAIRMUX_EVAL_ENV_FILE": str(env_file),
            "PAIRMUX_REAL_BIN": real_pairmux,
            "PAIRMUX_BIN": real_pairmux,
            "PAIRMUX_SOCKET": socket_name,
            "PAIRMUX_STATE_DIR": str(state_dir),
            "TMUX_TMPDIR": tmux_tmpdir,
            "PAIRMUX_STATE_NAMESPACE": str(state_namespace),
        }
    )

    setup_result = run_process(
        [str(control_scenario / "setup.sh")],
        cwd=scenario_dir,
        env=setup_env,
        stdout_path=evidence_dir / "setup.stdout.log",
        stderr_path=evidence_dir / "setup.stderr.log",
        timeout=min(timeout, 60.0),
    )
    agent_result: ProcessResult | None = None
    check_result: ProcessResult | None = None
    transcript_path = evidence_dir / "transcript.jsonl"
    calls_path = evidence_dir / "pairmux-calls.jsonl"
    rejections_path = evidence_dir / "broker-rejections.jsonl"
    proof_path = evidence_dir / "trace-proof.json"
    calls: list[dict[str, object]] = []
    rejections: list[dict[str, object]] = []
    trace_errors: list[str] = []
    scenario_trace_errors: list[str] = []
    project_isolation: dict[str, object] = {
        "method": "not-run",
        "path": str(scenario_dir),
        "commit": None,
    }
    discovery: dict[str, object] = {
        "verified": False,
        "method": "not-run",
        "path": str(skill_dir / "SKILL.md"),
    }
    broker: PairmuxBroker | None = None
    try:
        if setup_result.returncode == 0 and not setup_result.timed_out and not setup_result.start_error:
            if not env_file.is_file():
                raise RuntimeError("setup did not create runner-controlled env.sh")
            control_hashes[env_file] = sha256_file(env_file)
            env_file.chmod(0o444)
            verify_hashes(control_hashes)

            project_isolation = prepare_agent_project_isolation(
                agent=agent,
                scenario_dir=scenario_dir,
                env=clean_env,
            )

            discovery = verify_skill_discovery(
                agent=agent,
                executable=agent_executable,
                agent_version=agent_version,
                env=clean_env,
                cwd=scenario_dir,
                skill_dir=skill_dir,
                host_home=host_home,
                evidence_path=evidence_dir / "skill-discovery.log",
                model=model,
                claude_sentinel_token=claude_sentinel_token,
            )

            agent_env = clean_env.copy()
            agent_env.update(
                {
                    "PATH": str(proxy_dir) + os.pathsep + clean_env.get("PATH", ""),
                    "PAIRMUX_BIN": str(proxy_path),
                    "PAIRMUX_EVAL_PROXY_DIR": str(proxy_dir),
                    "PAIRMUX_EVAL_PROXY_BIN": str(proxy_path),
                    "PAIRMUX_SOCKET": socket_name,
                    "PAIRMUX_STATE_DIR": str(state_dir),
                    "TMUX_TMPDIR": tmux_tmpdir,
                    "PAIRMUX_STATE_NAMESPACE": str(state_namespace),
                }
            )
            agent_env.update(shell_path_guard)
            broker_env = clean_env.copy()
            broker_env.update(
                {
                    "PAIRMUX_BIN": str(real_proxy_target),
                    "PAIRMUX_REAL_BIN": str(real_proxy_target),
                    "PAIRMUX_SOCKET": socket_name,
                    "PAIRMUX_STATE_DIR": str(state_dir),
                    "TMUX_TMPDIR": tmux_tmpdir,
                    "PAIRMUX_STATE_NAMESPACE": str(state_namespace),
                }
            )
            broker = PairmuxBroker(
                control_runtime / "broker.sock",
                real_pairmux=real_proxy_target,
                real_pairmux_sha256=pairmux_sha256,
                fixed_env=broker_env,
                allowed_cwd=work_root,
                expected_socket=socket_name,
            )
            broker.start()
            try:
                agent_result = run_process(
                    agent_argv,
                    cwd=scenario_dir,
                    env=agent_env,
                    stdout_path=transcript_path,
                    stderr_path=evidence_dir / "agent.stderr.log",
                    timeout=timeout,
                    cleanup_group=True,
                    timeout_observer=broker.inflight_at_timeout,
                )
            finally:
                trace = broker.stop_and_finalize()
            calls = trace.calls
            trace_errors = trace.errors
            rejections = trace.rejections
            write_broker_calls(calls_path, calls)
            write_broker_rejections(rejections_path, rejections)
            if not skill_dir.is_dir() or sha256_tree(skill_dir) != skill_tree_sha256:
                trace_errors.append("installed skill changed while the agent was running")
            scenario_trace_errors = validate_scenario_calls(scenario, calls)
            proof = {
                "schema": "pairmux.eval.trace-proof.v1",
                "scenario": scenario,
                "valid": not trace_errors and not scenario_trace_errors,
                "errors": [*trace_errors, *scenario_trace_errors],
            }
            atomic_json(proof_path, proof)

            check_env = setup_env.copy()
            check_env.update(
                {
                    "PAIRMUX_EVAL_CALLS_FILE": str(calls_path),
                    "PAIRMUX_EVAL_TRACE_PROOF": str(proof_path),
                }
            )
            verify_hashes(control_hashes)
            check_result = run_process(
                [str(control_scenario / "check.sh"), str(transcript_path)],
                cwd=scenario_dir,
                env=check_env,
                stdout_path=evidence_dir / "check.stdout.log",
                stderr_path=evidence_dir / "check.stderr.log",
                timeout=min(timeout, 60.0),
            )
        else:
            transcript_path.touch()
            calls_path.touch()
            rejections_path.touch()
    finally:
        if broker is not None:
            broker.stop_and_finalize()
        cleanup_tmux(socket_name, setup_env, evidence_dir / "cleanup.log")
        shutil.rmtree(Path(shell_path_guard["BASH_ENV"]).parent, ignore_errors=True)

        for name in (
            "setup.stdout.log",
            "setup.stderr.log",
            "agent.stderr.log",
            "check.stdout.log",
            "check.stderr.log",
            "cleanup.log",
            "transcript.jsonl",
            "pairmux-calls.jsonl",
            "broker-rejections.jsonl",
            "trace-proof.json",
            "skill-discovery.log",
        ):
            source = evidence_dir / name
            if source.is_file():
                shutil.copy2(source, episode_root / name)
        if env_file.is_file():
            shutil.copy2(env_file, artifact_root / "env.sh")
        if skill_dir.is_dir():
            shutil.copytree(skill_dir, skill_artifact_dir)
        else:
            skill_artifact_dir.mkdir()
        state_artifact = artifact_root / "state"
        if state_dir.is_dir():
            shutil.copytree(state_dir, state_artifact)
        control_manifest = {
            "schema": "pairmux.eval.control-manifest.v1",
            "control_root_exposed_in_task": False,
            "worktree_contains_control_scripts": False,
            "proxy_trace_transport": "runner-owned-execution-broker",
            "broker_ledger_serialized_after_agent": True,
            "broker_request_can_report_evidence": False,
            "broker_denied_cwd_requests_are_audited": True,
            "nonfatal_broker_policy_rejection_codes": ["cwd-outside-work-root"],
            "host_home_inherited": False,
            "agent_project_isolation": project_isolation,
            "skill_discovery_path": skill_discovery_path,
            "skill_tree_sha256": skill_tree_sha256,
            "control_source_sha256": {
                str(path.relative_to(control_root)): digest for path, digest in control_hashes.items()
            },
        }
        atomic_json(artifact_root / "control-manifest.json", control_manifest)
        shutil.rmtree(control_root, ignore_errors=True)

    category = failure_class(setup_result, agent_result, check_result)
    expected_handoff = bool(
        scenario == "S05"
        and agent_result
        and agent_result.timed_out
        and check_result
        and check_result.returncode == 0
        and not trace_errors
        and not scenario_trace_errors
        and s05_handoff_call(calls) is not None
    )
    if expected_handoff:
        category = None
        outcome = "expected_human_handoff"
    elif scenario == "S05" and category is None:
        # S05 is intentionally unfinishable without a human. A normal agent
        # exit after a short --timeout is not a handoff, even if the fixture
        # check otherwise observed the right command text.
        category = "handoff_not_blocking"
        outcome = "failed"
    elif category is None:
        outcome = "passed"
    else:
        outcome = "failed"
    finished_at = utc_now()
    result: dict[str, object] = {
        "schema": RESULT_SCHEMA,
        "run_id": run_id,
        "episode_id": episode_id,
        "agent": agent,
        "agent_version": agent_version,
        "model": model or "default",
        "provider": provider or inferred_provider(model) or "unverified-default",
        "provider_verified": provider is not None,
        "scenario": scenario,
        "repeat": repetition,
        "pass": category is None,
        "outcome": outcome,
        "steps": len(calls),
        "wall_time_seconds": round(time.monotonic() - episode_started, 6),
        "failure_class": category,
        "started_at": episode_started_at,
        "finished_at": finished_at,
        "timeout_seconds": timeout,
        "timed_out": bool(agent_result and agent_result.timed_out),
        "agent_group_cleanup_signal": agent_result.termination_signal if agent_result else None,
        "setup_exit_code": setup_result.returncode,
        "agent_exit_code": agent_result.returncode if agent_result else None,
        "check_exit_code": check_result.returncode if check_result else None,
        "socket": socket_name,
        "state_dir": relative(artifact_root / "state", run_root),
        "state_namespace": relative(
            artifact_root / "state" / state_namespace.relative_to(state_dir), run_root
        ),
        "task_sha256": task_sha256,
        "scenario_source_sha256": scenario_source_hashes(scenario),
        "git": completed_git_provenance(git_start),
        "agent_argv": agent_argv,
        "pairmux_version": pairmux_version,
        "pairmux_path": real_pairmux,
        "pairmux_sha256": pairmux_sha256,
        "skill_source": str(SKILL_SOURCE),
        "skill_install_dir": relative(skill_artifact_dir, run_root),
        "skill_discovery_path": skill_discovery_path,
        "skill_discovery_home": str(isolated_home),
        "skill_discovery_verified": discovery.get("verified") is True,
        "skill_discovery": discovery,
        "skill_tree_sha256": skill_tree_sha256,
        "skill_md_sha256": skill_md_sha256,
        "shell_path_guard": {
            "artifact": relative(artifact_root / "control-manifest.json", run_root),
            "activation_paths_removed": True,
        },
        "agent_project_isolation": project_isolation,
        "broker_policy_rejections": len(rejections),
        "trace_validation_errors": trace_errors,
        "scenario_trace_errors": scenario_trace_errors,
        "paths": {
            "episode": relative(episode_root, run_root),
            "transcript": relative(episode_root / "transcript.jsonl", run_root),
            "pairmux_calls": relative(episode_root / "pairmux-calls.jsonl", run_root),
            "broker_rejections": relative(
                episode_root / "broker-rejections.jsonl", run_root
            ),
            "check_stdout": relative(episode_root / "check.stdout.log", run_root),
            "check_stderr": relative(episode_root / "check.stderr.log", run_root),
            "control_manifest": relative(artifact_root / "control-manifest.json", run_root),
        },
    }
    if setup_result.start_error:
        result["error"] = setup_result.start_error
    elif agent_result and agent_result.start_error:
        result["error"] = agent_result.start_error
    elif check_result and check_result.start_error:
        result["error"] = check_result.start_error
    atomic_json(episode_root / "result.json", result)
    return result


def make_run_root(output_dir: Path) -> tuple[str, Path]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for _attempt in range(20):
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        run_id = f"{timestamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        run_root = output_dir / run_id
        try:
            run_root.mkdir()
        except FileExistsError:
            continue
        return run_id, run_root
    raise RuntimeError(f"could not allocate a unique run directory under {output_dir}")


def acceptance_status(
    *,
    profile: str,
    agent: str,
    provider_verified: bool,
    model_verified: bool,
    results: list[dict[str, object]],
    git: object,
) -> dict[str, object]:
    requirements = {
        "claude": (tuple(f"S{number:02d}" for number in range(1, 10)), 1, 1.0),
        "codex": (("S01", "S02", "S03", "S04", "S05", "S06", "S08"), 1, 1.0),
        "opencode": (tuple(f"S{number:02d}" for number in range(1, 11)), 3, 1.0),
    }
    scenarios, minimum_repetitions, threshold = requirements[agent]
    reasons: list[str] = []
    if profile != "p4":
        reasons.append("P4 acceptance profile was not requested")
    if not provider_verified:
        reasons.append("provider was not explicitly recorded with --provider")
    if not model_verified:
        reasons.append("model was not explicitly recorded with --model")
    if (
        not isinstance(git, dict)
        or not isinstance(git.get("commit"), str)
        or not git.get("commit")
        or git.get("dirty") is not False
        or git.get("stable") is not True
    ):
        reasons.append("git checkout is dirty or provenance is unavailable")
    for scenario in scenarios:
        items = [item for item in results if item.get("scenario") == scenario]
        if len(items) < minimum_repetitions:
            reasons.append(f"{scenario} has {len(items)}/{minimum_repetitions} required repetitions")
            continue
        rate = sum(1 for item in items if item.get("pass") is True) / len(items)
        if rate < threshold:
            reasons.append(f"{scenario} pass rate {rate:.3f} is below {threshold:.3f}")
    return {
        "profile": profile,
        "required_scenarios": list(scenarios),
        "minimum_repetitions": minimum_repetitions,
        "pass_rate_threshold": threshold,
        "eligible": not reasons,
        "reasons": reasons,
    }


def summarize(
    *,
    run_root: Path,
    run_id: str,
    started_at: str,
    started_monotonic: float,
    agent: str,
    agent_version: str,
    model: str | None,
    provider: str | None,
    acceptance_profile: str,
    codex_sandbox: str,
    pairmux_version: str,
    pairmux_path: str,
    pairmux_sha256: str,
    skill_tree_sha256: str,
    skill_md_sha256: str,
    git_start: dict[str, object],
    results: list[dict[str, object]],
) -> dict[str, object]:
    passed = sum(1 for item in results if item["pass"])
    total = len(results)
    scenarios: dict[str, dict[str, object]] = {}
    for scenario in sorted({str(item["scenario"]) for item in results}):
        items = [item for item in results if item["scenario"] == scenario]
        scenario_passed = sum(1 for item in items if item["pass"])
        scenarios[scenario] = {
            "episodes": len(items),
            "passed": scenario_passed,
            "pass_rate": round(scenario_passed / len(items), 6),
            "steps": sum(int(item["steps"]) for item in items),
            "broker_policy_rejections": sum(
                int(item["broker_policy_rejections"]) for item in items
            ),
            "wall_time_seconds": round(sum(float(item["wall_time_seconds"]) for item in items), 6),
        }
    summary: dict[str, object] = {
        "schema": SUMMARY_SCHEMA,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": utc_now(),
        "wall_time_seconds": round(time.monotonic() - started_monotonic, 6),
        "agent": agent,
        "agent_version": agent_version,
        "model": model or "default",
        "provider": provider or inferred_provider(model) or "unverified-default",
        "provider_verified": provider is not None,
        "codex_sandbox": codex_sandbox if agent == "codex" else None,
        "pairmux_version": pairmux_version,
        "pairmux_path": pairmux_path,
        "pairmux_sha256": pairmux_sha256,
        "skill_source": str(SKILL_SOURCE),
        "skill_tree_sha256": skill_tree_sha256,
        "skill_md_sha256": skill_md_sha256,
        "totals": {
            "episodes": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 6) if total else 0.0,
            "steps": sum(int(item["steps"]) for item in results),
            "broker_policy_rejections": sum(
                int(item["broker_policy_rejections"]) for item in results
            ),
        },
        "scenarios": scenarios,
        "results": results,
    }
    summary["git"] = completed_git_provenance(git_start)
    summary["fixture_sha256"] = {
        scenario: scenario_source_hashes(scenario)
        for scenario in sorted({str(item["scenario"]) for item in results})
    }
    summary["acceptance"] = acceptance_status(
        profile=acceptance_profile,
        agent=agent,
        provider_verified=provider is not None,
        model_verified=model is not None,
        results=results,
        git=summary["git"],
    )
    atomic_json(run_root / "summary.json", summary)
    write_summary_markdown(run_root / "summary.md", summary)
    return summary


def write_summary_markdown(path: Path, summary: dict[str, object]) -> None:
    totals = summary["totals"]
    assert isinstance(totals, dict)
    results = summary["results"]
    assert isinstance(results, list)
    lines = [
        "# pairmux eval summary",
        "",
        f"- Run: `{summary['run_id']}`",
        f"- Agent: `{summary['agent']}` (`{summary['agent_version']}`)",
        f"- Model: `{summary['model']}`",
        f"- Pairmux: `{summary['pairmux_version']}`",
        f"- Pairmux binary: `{summary['pairmux_path']}` (`{summary['pairmux_sha256']}`)",
        f"- Skill tree: `{summary['skill_tree_sha256']}`",
        f"- Result: **{totals['passed']}/{totals['episodes']} passed** ({float(totals['pass_rate']) * 100:.1f}%)",
        f"- Broker policy rejections: {totals['broker_policy_rejections']}",
        f"- Wall time: {float(summary['wall_time_seconds']):.3f}s",
        f"- Acceptance eligible: **{str(bool(summary['acceptance']['eligible'])).lower()}** "
        f"(`{summary['acceptance']['profile']}`)",
        "",
        "| scenario | repeat | result | executed steps | policy rejections | wall time | failure class |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    for item in results:
        status = str(item.get("outcome", "passed" if item["pass"] else "failed"))
        failure = item["failure_class"] or "-"
        lines.append(
            f"| {item['scenario']} | {item['repeat']} | {status} | {item['steps']} | "
            f"{item['broker_policy_rejections']} | {float(item['wall_time_seconds']):.3f}s | "
            f"{failure} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=("opencode", "claude", "codex"))
    parser.add_argument(
        "--model", type=non_empty_text, help="agent model identifier (agent default when omitted)"
    )
    parser.add_argument(
        "--provider", type=non_empty_text, help="actual model provider; required for acceptance evidence"
    )
    parser.add_argument(
        "--acceptance-profile",
        choices=("none", "p4"),
        default="none",
        help="evaluate explicit scenario/repetition/pass-rate provenance (default: none)",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="scenario or ascending range; repeatable (examples: S01, 2-5, S01-S06)",
    )
    parser.add_argument("--repeat", type=positive_int, default=1, help="episodes per scenario (default: 1)")
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=180.0,
        help="wall-clock agent timeout per episode in seconds (default: 180)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=EVALS_DIR / "runs",
        help="parent directory for unique run directories (default: evals/runs)",
    )
    parser.add_argument(
        "--pairmux-bin",
        type=Path,
        help="pairmux binary under test (default: built sibling, then PAIRMUX_REAL_BIN/PATH)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print episode argv as JSON without executing")
    parser.add_argument(
        "--codex-sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="danger-full-access",
        help="Codex sandbox; danger-full-access is the tmux-compatible default",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    model_provider = inferred_provider(args.model)
    if args.provider and model_provider and args.provider != model_provider:
        parser.error(
            f"--provider {args.provider!r} does not match model prefix {model_provider!r}"
        )
    try:
        scenarios = parse_scenarios(args.scenario, discover_scenarios())
    except ValueError as error:
        parser.error(str(error))

    agent_executable = shutil.which(args.agent) or args.agent
    if args.dry_run:
        for scenario in scenarios:
            task = (SCENARIOS_DIR / scenario / "TASK.md").read_text(encoding="utf-8")
            for repetition in range(1, args.repeat + 1):
                plan = {
                    "agent": args.agent,
                    "model": args.model or "default",
                    "scenario": scenario,
                    "repeat": repetition,
                    "cwd": str(SCENARIOS_DIR / scenario),
                    "argv": build_agent_argv(
                        args.agent,
                        agent_executable,
                        task,
                        args.model,
                        args.codex_sandbox,
                        working_directory=SCENARIOS_DIR / scenario,
                    ),
                }
                print(json.dumps(plan, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
        return 0

    if not shutil.which(args.agent):
        parser.error(f"{args.agent!r} is not executable on PATH")
    try:
        real_pairmux = resolve_pairmux(args.pairmux_bin)
    except ValueError as error:
        parser.error(str(error))
    if not real_pairmux:
        parser.error("pairmux is not executable on PATH and no sibling pairmux build was found")
    if not PROXY_SOURCE.is_file():
        parser.error(f"pairmux proxy is missing: {PROXY_SOURCE}")
    if not SKILL_SOURCE.is_dir() or not (SKILL_SOURCE / "SKILL.md").is_file():
        parser.error(f"canonical pairmux skill is missing: {SKILL_SOURCE}")

    run_started_at = utc_now()
    run_started = time.monotonic()
    git_start = git_provenance()
    run_id, run_root = make_run_root(args.output_dir)
    agent_executable = str(Path(shutil.which(args.agent) or args.agent).resolve())
    agent_version = probe_version(agent_executable)
    pairmux_version = probe_version(real_pairmux)
    pairmux_sha256 = sha256_file(Path(real_pairmux))
    skill_tree_sha256 = sha256_tree(SKILL_SOURCE)
    skill_md_sha256 = sha256_file(SKILL_SOURCE / "SKILL.md")
    results_path = run_root / "results.jsonl"
    results: list[dict[str, object]] = []

    with results_path.open("w", encoding="utf-8") as results_stream:
        for scenario in scenarios:
            for repetition in range(1, args.repeat + 1):
                try:
                    result = run_episode(
                        run_root=run_root,
                        run_id=run_id,
                        scenario=scenario,
                        repetition=repetition,
                        agent=args.agent,
                        agent_executable=agent_executable,
                        agent_version=agent_version,
                        model=args.model,
                        provider=args.provider,
                        codex_sandbox=args.codex_sandbox,
                        real_pairmux=real_pairmux,
                        pairmux_version=pairmux_version,
                        pairmux_sha256=pairmux_sha256,
                        git_start=git_start,
                        timeout=args.timeout,
                    )
                except Exception as error:  # Keep later episodes runnable after a harness failure.
                    failure_root = run_root / "episodes" / f"{scenario}-r{repetition:02d}-runner-error"
                    failure_root.mkdir(parents=True, exist_ok=True)
                    (failure_root / "traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
                    result = {
                        "schema": RESULT_SCHEMA,
                        "run_id": run_id,
                        "episode_id": failure_root.name,
                        "agent": args.agent,
                        "agent_version": agent_version,
                        "model": args.model or "default",
                        "provider": args.provider or inferred_provider(args.model) or "unverified-default",
                        "provider_verified": args.provider is not None,
                        "scenario": scenario,
                        "repeat": repetition,
                        "pass": False,
                        "outcome": "failed",
                        "steps": 0,
                        "wall_time_seconds": 0.0,
                        "failure_class": "runner_error",
                        "error": f"{type(error).__name__}: {error}",
                        "pairmux_version": pairmux_version,
                        "pairmux_path": real_pairmux,
                        "pairmux_sha256": pairmux_sha256,
                        "skill_source": str(SKILL_SOURCE),
                        "skill_tree_sha256": skill_tree_sha256,
                        "skill_md_sha256": skill_md_sha256,
                        "git": completed_git_provenance(git_start),
                        "paths": {"episode": relative(failure_root, run_root)},
                    }
                    atomic_json(failure_root / "result.json", result)
                results.append(result)
                json.dump(result, results_stream, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
                results_stream.write("\n")
                results_stream.flush()
                status = "PASS" if result["pass"] else "FAIL"
                print(
                    f"{status} {scenario} repeat={repetition} steps={result['steps']} "
                    f"wall={float(result['wall_time_seconds']):.3f}s "
                    f"failure={result['failure_class'] or '-'}",
                    file=sys.stderr,
                )

    summary = summarize(
        run_root=run_root,
        run_id=run_id,
        started_at=run_started_at,
        started_monotonic=run_started,
        agent=args.agent,
        agent_version=agent_version,
        model=args.model,
        provider=args.provider,
        acceptance_profile=args.acceptance_profile,
        codex_sandbox=args.codex_sandbox,
        pairmux_version=pairmux_version,
        pairmux_path=real_pairmux,
        pairmux_sha256=pairmux_sha256,
        skill_tree_sha256=skill_tree_sha256,
        skill_md_sha256=skill_md_sha256,
        git_start=git_start,
        results=results,
    )
    print(run_root)
    totals = summary["totals"]
    assert isinstance(totals, dict)
    acceptance = summary["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance_failed = args.acceptance_profile == "p4" and acceptance.get("eligible") is not True
    return 0 if totals["failed"] == 0 and not acceptance_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
