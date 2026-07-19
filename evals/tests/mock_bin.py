#!/usr/bin/env python3
"""Mock agent and pairmux executables for eval runner tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time


def append_json(path_value: str | None, payload: dict[str, object]) -> None:
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
        stream.write("\n")


def run_pairmux(args: list[str]) -> int:
    if args == ["--version"]:
        print("pairmux mock-1.0")
        return 0
    if args and args[0] == "mock-fail":
        print("broker stdout preserved")
        print("broker stderr preserved", file=sys.stderr)
        return 23
    command_index = next(
        (index for index, value in enumerate(args) if value in {"new", "run", "peek", "wait", "log", "send"}),
        None,
    )
    if command_index is None:
        return 0
    command = args[command_index]
    state_dir = Path(os.environ["PAIRMUX_STATE_DIR"])
    if command == "new":
        if "--name" in args:
            terminal = args[args.index("--name") + 1]
        else:
            terminal = "mock"
        terminal_dir = state_dir / terminal
        terminal_dir.mkdir(parents=True, exist_ok=True)
        (terminal_dir / "raw.log").touch()
        (terminal_dir / "index.jsonl").touch()
        print('{"schema":"pairmux.v1","ok":true,"status":"created"}')
        return 0
    if command == "run":
        terminal = args[command_index + 1]
        command_text = args[command_index + 2]
        if "HANG-FOREVER" in command_text:
            time.sleep(60)
            return 0
        terminal_dir = state_dir / terminal
        terminal_dir.mkdir(parents=True, exist_ok=True)
        with (terminal_dir / "raw.log").open("a", encoding="utf-8") as stream:
            if "PAIRMUX-S01-OK" in command_text:
                stream.write("PAIRMUX-S01-OK\n")
            elif "secret.sh" in command_text:
                stream.write("Enter deployment password:\n")
            else:
                stream.write(command_text + "\n")
        print('{"schema":"pairmux.v1","ok":true,"status":"done","exit_code":0}')
        return 0
    if command == "wait" and "--human" in args[command_index + 1 :]:
        if os.environ.get("PAIRMUX_MOCK_MODE") == "completed_handoff":
            print('{"schema":"pairmux.v1","ok":true,"status":"timeout"}')
            return 0
        time.sleep(60)
        return 0
    return 0


def emit_transcript(program: str) -> None:
    if program == "claude":
        print(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "input": {"command": "pairmux new --name mock"},
                            },
                            {
                                "type": "tool_use",
                                "input": {
                                    "command": "pairmux run mock \\\"printf PAIRMUX-S01-OK\\\""
                                },
                            },
                            {"type": "text", "text": "pairmux finished with exit code 0"},
                        ]
                    },
                }
            )
        )
    elif program == "opencode":
        print(
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "type": "tool",
                        "tool": "bash",
                        "state": {"input": {"command": "pairmux new --name mock"}},
                    },
                }
            )
        )
        print(json.dumps({"type": "text", "part": {"text": "exit code 0"}}))
    else:
        print(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "pairmux new --name mock",
                        "aggregated_output": "fixture output is not issued content",
                    },
                }
            )
        )
        print(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "exit code 0"},
                }
            )
        )


def run_agent(program: str, args: list[str]) -> int:
    if args == ["--version"]:
        print(f"{program} mock-1.0")
        return 0
    task_arguments = [value for value in args if "\n" in value and "pairmux" in value.lower()]
    home = Path(os.environ["HOME"])
    skill_paths = {
        "opencode": Path(os.environ["XDG_CONFIG_HOME"]) / "opencode/skills/pairmux/SKILL.md",
        "claude": Path.cwd().parent / ".claude/skills/pairmux/SKILL.md",
        "codex": home / ".agents/skills/pairmux/SKILL.md",
    }
    skill_path = skill_paths[program]
    append_json(
        os.environ.get("PAIRMUX_MOCK_AGENT_LOG"),
        {
            "program": program,
            "argv": args,
            "task_arguments": task_arguments,
            "loaded_skill": str(skill_path),
            "loaded_skill_exists": skill_path.is_file(),
            "home": str(home),
            "xdg_config_home": os.environ.get("XDG_CONFIG_HOME"),
            "codex_home": os.environ.get("CODEX_HOME"),
            "codex_home_exists": Path(os.environ["CODEX_HOME"]).is_dir(),
            "claude_config_dir": os.environ.get("CLAUDE_CONFIG_DIR"),
            "host_poison": os.environ.get("PAIRMUX_HOST_POISON"),
            "real_bin_exposed": os.environ.get("PAIRMUX_REAL_BIN"),
            "opencode_disable_project_config": os.environ.get(
                "OPENCODE_DISABLE_PROJECT_CONFIG"
            ),
        },
    )
    if len(task_arguments) != 1:
        print("mock agent expected TASK.md content as exactly one argv element", file=sys.stderr)
        return 64
    if not skill_path.is_file():
        print("mock agent expected a canonical skill in isolated discovery config", file=sys.stderr)
        return 65

    def pairmux(*pairmux_args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["pairmux", *pairmux_args],
            check=check,
        )

    mode = os.environ.get("PAIRMUX_MOCK_MODE", "pass")
    if mode == "hang":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        append_json(os.environ.get("PAIRMUX_MOCK_CHILD_LOG"), {"pid": child.pid})
        time.sleep(60)
        return 0
    if mode == "hang_pairmux":
        pairmux("run", "mock", "HANG-FOREVER", check=False)
        return 0
    if mode == "human_handoff":
        pairmux("new", "--name", "secret")
        pairmux("run", "secret", "./secret.sh", check=False)
        pairmux("wait", "secret", "--human", "--notify", check=False)
        return 0
    if mode == "completed_handoff":
        pairmux("new", "--name", "secret")
        pairmux("run", "secret", "./secret.sh", check=False)
        pairmux("wait", "secret", "--human", "--timeout", "1ms", check=False)
        print(
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "input": {
                                "command": "pairmux wait secret --human --timeout 1ms"
                            }
                        },
                    },
                }
            )
        )
        return 0
    if mode == "fail":
        return 7
    if mode == "mutate_skill":
        skill_path.chmod(0o644)
        skill_path.write_text("tampered\n", encoding="utf-8")
    if mode == "forge_trace_file":
        Path("agent-forged.json").write_text(
            '{"schema":"pairmux.eval.call.v1","argv":["wait","fake","--human"]}\n',
            encoding="utf-8",
        )
    if mode == "forge_broker_evidence":
        endpoint = Path(os.environ["PAIRMUX_BIN"]).resolve().parent.parent / "broker.sock"
        forged = json.dumps(
            {
                "schema": "pairmux.eval.call.v1",
                "argv": ["run", "mock", "printf PAIRMUX-S01-OK"],
                "cwd": os.getcwd(),
                "pid": os.getpid(),
                "exit_code": 0,
            },
            separators=(",", ":"),
        ).encode()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(endpoint))
            client.sendall(struct.pack("!I", len(forged)) + forged)
            client.shutdown(socket.SHUT_WR)
            client.recv(4096)
    if mode == "source_env":
        env_file = Path(os.environ["PAIRMUX_STATE_DIR"]).parent / "env.sh"
        subprocess.run(
            [
                "bash",
                "-c",
                '. "$1"; pairmux new --name mock; '
                "pairmux run mock \"printf '%s\\n' PAIRMUX-S01-OK\"",
                "source-env",
                str(env_file),
            ],
            check=True,
        )
        emit_transcript(program)
        return 0

    pairmux("new", "--name", "mock")
    pairmux("run", "mock", "printf '%s\\n' PAIRMUX-S01-OK")
    emit_transcript(program)
    return 0


def main() -> int:
    program = Path(sys.argv[0]).name
    args = sys.argv[1:]
    if program in {"pairmux", "real-pairmux"}:
        return run_pairmux(args)
    return run_agent(program, args)


if __name__ == "__main__":
    raise SystemExit(main())
