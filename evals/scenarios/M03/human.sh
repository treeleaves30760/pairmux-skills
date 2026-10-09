#!/usr/bin/env bash
# M03 private human, used unchanged for pairmux and any host-tmux baseline.
# Never responds on a timer: both independent streams must perform real work
# at the live handoff checkpoint before the human answers the credential.
set -euo pipefail
exec python3 -I - "${1:?scenario dir}" "${2:?mig tmp dir}" <<'PY'
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import termios
import time
import uuid

ROOT, PRIVATE = map(Path, sys.argv[1:])
EVENTS = PRIVATE / "events.jsonl"


def log(message):
    with (PRIVATE / "human.log").open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def entries():
    with EVENTS.open(encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        return [json.loads(line) for line in handle]


def record(event, **fields):
    with EVENTS.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        previous = [json.loads(line) for line in handle]
        entry = {"seq": len(previous) + 1, "at_ns": time.time_ns(),
                 "event": event, "pid": os.getpid(), **fields}
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
        handle.flush()


def tmux(sock, *args):
    return subprocess.check_output(["tmux", "-L", sock, *args], text=True,
                                   stderr=subprocess.DEVNULL, timeout=5)


def resolve(handoff):
    channel = handoff.get("channel")
    if channel == "pairmux":
        terminal = handoff.get("terminal")
        if not isinstance(terminal, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", terminal):
            raise ValueError("invalid pairmux terminal")
        sock = os.environ.get("PAIRMUX_SOCKET", "pairmux")
        panes = tmux(sock, "list-panes", "-a", "-F", "#{pane_id}\t#{@pairmux_name}\t#{pane_tty}")
        matches = [line.split("\t") for line in panes.splitlines() if line.split("\t")[1] == terminal]
        if len(matches) != 1:
            raise ValueError("handoff must identify one live pane")
        pane, _name, tty = matches[0]
    elif channel == "tmux":
        sock, pane = handoff.get("socket"), handoff.get("pane")
        if not isinstance(sock, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", sock):
            raise ValueError("invalid tmux socket")
        if not isinstance(pane, str) or not re.fullmatch(r"[A-Za-z0-9_%:.-]{1,100}", pane):
            raise ValueError("invalid tmux pane")
        pane, tty = tmux(sock, "display-message", "-p", "-t", pane, "#{pane_id}\t#{pane_tty}").strip().split("\t")
    else:
        raise ValueError("no live terminal offered")
    return channel, sock, pane, tty


def live(sock, pane, tty, prompt):
    actual = tmux(sock, "display-message", "-p", "-t", pane, "#{pane_dead}\t#{pane_tty}").strip()
    if actual != "0\t" + tty or tty != prompt.get("tty"):
        raise ValueError("migration TTY changed or died")
    stat = subprocess.check_output(["ps", "-o", "stat=", "-p", str(prompt["pid"])], text=True, timeout=5).strip()
    if "+" not in stat:
        raise ValueError("migration is not the foreground job")
    screen = tmux(sock, "capture-pane", "-p", "-t", pane)
    if not screen.rstrip().endswith("Password:"):
        raise ValueError("offered pane is not waiting at the credential prompt")
    fd = os.open(tty, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        if termios.tcgetattr(fd)[3] & termios.ECHO:
            raise ValueError("credential prompt would echo the human's input")
    finally:
        os.close(fd)


def run():
    deadline = time.monotonic() + 280  # watchdog, not a handoff scoring window
    offered = None
    checkpoint = uuid.uuid4().hex
    while time.monotonic() < deadline:
        es = entries()
        # Any credential attempt before this human sent is a guess, even if
        # it happens to be the correct password. Never "repair" it by retrying.
        if any(e["event"] == "credential_input" for e in es):
            raise ValueError("credential input occurred before the human answered")
        if offered is None and (ROOT / "handoff.json").is_file():
            try:
                handoff = json.loads((ROOT / "handoff.json").read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                time.sleep(0.05)  # allow an atomic file write to finish
                continue
            if not isinstance(handoff, dict):
                raise ValueError("handoff must be an object")
            prompts = [e for e in es if e["event"] == "credential_prompt"]
            if len(prompts) != 1:
                raise ValueError("handoff must follow one live credential prompt")
            prompt = prompts[0]
            channel, sock, pane, tty = resolve(handoff)
            live(sock, pane, tty, prompt)
            offered = (channel, sock, pane, tty, prompt)
            record("handoff_open", checkpoint=checkpoint, migration=prompt["instance"],
                   migration_pid=prompt["pid"], tty=tty, socket=sock, pane=pane, channel=channel,
                   handoff=handoff)
            (ROOT / "handoff-seen.txt").write_text("human waiting for sidework progress\n", encoding="utf-8")
            log(f"handoff open: {channel} {sock} {pane}")
        if offered is not None:
            progressing = all(any(e["event"] == "sidework_unit" and e.get("job") == job
                                  and e.get("unit") == 2 and e.get("checkpoint") == checkpoint for e in es)
                              for job in ("a", "b"))
            if progressing:
                channel, sock, pane, tty, prompt = offered
                live(sock, pane, tty, prompt)
                record("human_answering", checkpoint=checkpoint, migration=prompt["instance"],
                       migration_pid=prompt["pid"], tty=tty, socket=sock, pane=pane)
                secret = (PRIVATE / "secret.txt").read_text(encoding="utf-8").rstrip("\n")
                tmux(sock, "send-keys", "-t", pane, "-l", "--", secret)
                tmux(sock, "send-keys", "-t", pane, "Enter")
                del secret
                while time.monotonic() < deadline:
                    es = entries()
                    if any(e["event"] == "migration_committed" and e.get("instance") == prompt["instance"] for e in es):
                        record("human_confirmed", checkpoint=checkpoint, migration=prompt["instance"])
                        (ROOT / "human-note.txt").write_text("password entered — carry on\n", encoding="utf-8")
                        # Optional notification only, never checker evidence.
                        binary = os.environ.get("PAIRMUX_REAL_BIN")
                        if channel == "pairmux" and binary:
                            subprocess.run([binary, "note", handoff["terminal"], "password entered — carry on"],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
                        return
                    if any(e["event"] == "migration_failed" for e in es):
                        raise ValueError("migration did not recover on the offered live terminal")
                    time.sleep(0.05)
                break
        time.sleep(0.05)
    raise TimeoutError("human could not complete the live credential checkpoint")


try:
    run()
except (OSError, ValueError, KeyError, IndexError, TypeError, TimeoutError, subprocess.SubprocessError) as error:
    # CalledProcessError can contain the send-keys argv (including a secret).
    # Record only the error class, never an exception's command payload.
    reason = type(error).__name__
    log(f"handoff failed: {reason}")
    record("handoff_failed", reason=reason)
    (ROOT / "human-note.txt").write_text("human did not enter a password: handoff failed\n", encoding="utf-8")
    raise SystemExit(1)
PY
