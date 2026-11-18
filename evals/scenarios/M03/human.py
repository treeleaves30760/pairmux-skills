#!/usr/bin/env python3
"""M03 private human, used unchanged for pairmux and any host-tmux baseline.

Never responds on a timer: both independent streams must perform real work at the live handoff
checkpoint before the human answers the credential.

    human.py <scenario dir> <private dir>

A `tmux` channel, and a `pairmux` channel on the tmux backend, resolve the offered pane with tmux
itself. On pairmux's built-in backend (always on Windows) the pairmux channel is verified and
answered with the pairmux CLI only: the terminal must be live and awaiting input with its screen at
the `Password:` prompt, bound to the migration's own recorded terminal, and echo must be off.
"""
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

if evallib.IS_WINDOWS:
    import msvcrt
else:
    import fcntl
    import termios

ROOT, PRIVATE = map(Path, sys.argv[1:3])
EVENTS = PRIVATE / "events.jsonl"


def log(message):
    with (PRIVATE / "human.log").open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


@contextlib.contextmanager
def locked(handle, exclusive):
    """The fixture's own lock discipline (flock / one Windows byte past any data)."""
    if not evallib.IS_WINDOWS:
        fcntl.flock(handle, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
        return
    descriptor = os.open(EVENTS, os.O_RDWR | os.O_CREAT)
    try:
        os.lseek(descriptor, 1 << 30, os.SEEK_SET)
        while True:
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(0.01)
        try:
            yield
        finally:
            os.lseek(descriptor, 1 << 30, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(descriptor)


def entries():
    with EVENTS.open(encoding="utf-8") as handle, locked(handle, False):
        return [json.loads(line) for line in handle]


def record(event, **fields):
    with EVENTS.open("a+", encoding="utf-8") as handle, locked(handle, True):
        handle.seek(0)
        previous = [json.loads(line) for line in handle]
        entry = {"seq": len(previous) + 1, "at_ns": time.time_ns(),
                 "event": event, "pid": os.getpid(), **fields}
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
        handle.flush()


def tmux(sock, *args):
    return subprocess.check_output(["tmux", "-L", sock, *args], text=True,
                                   stderr=subprocess.DEVNULL, timeout=5)


def pairmux(*args):
    binary = os.environ.get("PAIRMUX_REAL_BIN") or evallib.pairmux_bin()
    completed = subprocess.run([binary, *args], text=True, encoding="utf-8", errors="replace",
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    return completed


def pairmux_json(*args):
    completed = pairmux("--json", *args)
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("pairmux could not read the offered terminal")
    return payload


def builtin_backend():
    return evallib.effective_backend() == "builtin"


def resolve(handoff):
    channel = handoff.get("channel")
    if channel == "pairmux":
        terminal = handoff.get("terminal")
        if not isinstance(terminal, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", terminal):
            raise ValueError("invalid pairmux terminal")
        sock = os.environ.get("PAIRMUX_SOCKET", "pairmux")
        if builtin_backend():
            # No pane to resolve: the terminal is its own identity; the TTY is the one the
            # migration recorded, bound below through pairmux's terminal directory.
            return channel, sock, terminal, None
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


def posix_tty_checks(tty, prompt):
    stat = subprocess.check_output(["ps", "-o", "stat=", "-p", str(prompt["pid"])], text=True, timeout=5).strip()
    if "+" not in stat:
        raise ValueError("migration is not the foreground job")
    fd = os.open(tty, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        if termios.tcgetattr(fd)[3] & termios.ECHO:
            raise ValueError("credential prompt would echo the human's input")
    finally:
        os.close(fd)


def live_builtin(terminal, prompt):
    peek = pairmux_json("peek", terminal)
    if peek.get("status") != "awaiting-input":
        raise ValueError("offered terminal is not waiting for input")
    screen = pairmux_json("peek", terminal, "--screen")
    if not str(screen.get("output", "")).rstrip().endswith("Password:"):
        raise ValueError("offered terminal is not waiting at the credential prompt")
    recorded = prompt.get("terminal_dir")
    if not isinstance(recorded, str) or not recorded:
        raise ValueError("migration did not run in a pairmux terminal")
    if Path(recorded).resolve() != evallib.terminal_dir(terminal).resolve():
        raise ValueError("offered terminal is not the migration's terminal")
    if not evallib.pid_alive(int(prompt["pid"])):
        raise ValueError("migration died")
    if evallib.IS_WINDOWS:
        # The fixture measured its own console input mode after disabling echo.
        if prompt.get("echo") is not False:
            raise ValueError("credential prompt would echo the human's input")
    else:
        posix_tty_checks(prompt.get("tty"), prompt)


def live(sock, pane, tty, prompt):
    if tty is None:
        live_builtin(pane, prompt)
        return
    actual = tmux(sock, "display-message", "-p", "-t", pane, "#{pane_dead}\t#{pane_tty}").strip()
    if actual != "0\t" + tty or tty != prompt.get("tty"):
        raise ValueError("migration TTY changed or died")
    posix_tty_checks(tty, prompt)
    screen = tmux(sock, "capture-pane", "-p", "-t", pane)
    if not screen.rstrip().endswith("Password:"):
        raise ValueError("offered pane is not waiting at the credential prompt")


def type_secret(sock, pane, tty, secret):
    if tty is None:
        completed = pairmux("send", pane, "--text", secret, "--enter")
        if completed.returncode != 0:
            raise ValueError("pairmux could not deliver the credential")
        return
    tmux(sock, "send-keys", "-t", pane, "-l", "--", secret)
    tmux(sock, "send-keys", "-t", pane, "Enter")


def read_handoff():
    path = ROOT / "handoff.json"
    text = evallib.read_answer(path) if evallib.IS_WINDOWS else path.read_text(encoding="utf-8")
    return json.loads(text)


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
                handoff = read_handoff()
            except (json.JSONDecodeError, UnicodeError):
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
            recorded_tty = tty if tty is not None else prompt.get("tty")
            offered = (channel, sock, pane, tty, prompt)
            record("handoff_open", checkpoint=checkpoint, migration=prompt["instance"],
                   migration_pid=prompt["pid"], tty=recorded_tty, socket=sock, pane=pane, channel=channel,
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
                       migration_pid=prompt["pid"], tty=tty if tty is not None else prompt.get("tty"),
                       socket=sock, pane=pane)
                secret = (PRIVATE / "secret.txt").read_text(encoding="utf-8").rstrip("\n")
                type_secret(sock, pane, tty, secret)
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
