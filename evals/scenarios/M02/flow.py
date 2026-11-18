#!/usr/bin/env python3
"""Real Python REPL and a terminal-only deployment/pager fixture."""
import code
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import termsupport  # noqa: E402


def record(event, **fields):
    ppid, sid, tty = termsupport.identity(0)
    row = dict(event=event, pid=os.getpid(), ppid=ppid, sid=sid,
               tty=tty, cwd=os.getcwd(), time_ns=termsupport.event_ns(), **fields)
    with (ROOT / "interaction.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def repl():
    class LiveConsole(code.InteractiveConsole):
        def raw_input(self, prompt=''):
            source = super().raw_input(prompt)
            record('repl_input', source=source)
            return source

    console = LiveConsole()
    original = sys.stdout

    class LiveOutput:
        pending = ''

        def write(self, text):
            result = original.write(text)
            self.pending += text
            while '\n' in self.pending:
                line, self.pending = self.pending.split('\n', 1)
                if line.strip().isdigit():
                    record('repl_result', value=int(line.strip()))
            return result

        def __getattr__(self, name):
            return getattr(original, name)

    record("repl_started")
    sys.stdout = LiveOutput()
    try:
        console.interact(banner="Compute the release value here, then exit the REPL.", exitmsg="")
    except SystemExit:
        pass
    finally:
        sys.stdout = original
    record("repl_exited")


def deploy(value):
    record("deploy_started", value=value)
    answer = input(f"Deploy release {value}? [Y/N] ")
    record("confirmation", answer=answer, value=value)
    if answer.lower() != "y":
        raise SystemExit("deployment declined")
    record("pager_entered", value=value)
    for number in range(1, 81):
        print(f"release {value}: review line {number:02d}")
    print("(END) — press q to leave the deployment report", flush=True)
    with termsupport.KeyReader() as keys:
        while True:
            key = keys.read()
            record("pager_key", key=key)
            if key == "q":
                break
    record("pager_exit", value=value)
    line = f"DEPLOYED release={value}"
    (ROOT / "deployment.txt").write_text(line + "\n", encoding="utf-8")
    record("deployment_complete", value=value)
    print("\n" + line, flush=True)


if __name__ == "__main__":
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SystemExit("This workflow needs a live terminal, not piped input/output.")
    if sys.argv[1:] == ["repl"]:
        repl()
    elif len(sys.argv) == 3 and sys.argv[1] == "deploy":
        deploy(int(sys.argv[2]))
    else:
        raise SystemExit("usage: python3 flow.py repl | python3 flow.py deploy VALUE")
