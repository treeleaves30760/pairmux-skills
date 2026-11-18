#!/usr/bin/env python3
"""M03 fixture (Windows twin of fake-sudo-migrate.sh): the same live migration console survives a
human-only credential checkpoint. Sideworkers share only this fixture's event writer."""
import contextlib
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import re
import signal
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # also when started isolated (-I)
import termsupport  # noqa: E402

config = (ROOT / ".mig-config").read_text(encoding="utf-8")
match = re.fullmatch(r"MIG_TMP=([A-Za-z]:\\[^\r\n]*\\pmx-m03-[A-Za-z0-9]+)\n", config)
if not match:
    raise SystemExit("error: invalid or missing scenario configuration")
PRIVATE = Path(match[1])
EVENTS = PRIVATE / "events.jsonl"


@contextlib.contextmanager
def locked():
    """One byte locked far past any data: unlocked readers never meet the mandatory lock."""
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
    with locked(), EVENTS.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def record(event, **fields):
    with locked(), EVENTS.open("a+", encoding="utf-8") as handle:
        handle.seek(0)
        previous = [json.loads(line) for line in handle]
        item = {"seq": len(previous) + 1, "at_ns": time.time_ns(),
                "event": event, "pid": os.getpid(), **fields}
        handle.write(json.dumps(item, sort_keys=True) + "\n")
        handle.flush()
        return item


def until(predicate):
    deadline = time.monotonic() + 280
    while time.monotonic() < deadline:
        result = predicate(entries())
        if result:
            return result
        time.sleep(0.05)  # fixture event coordination, never a scoring threshold
    raise TimeoutError("credential checkpoint was not reached")


def step():
    time.sleep(max(0.01, float(os.environ.get("EVAL_TIME_SCALE", "1"))))


def sidework(job):
    instance = uuid.uuid4().hex
    record("sidework_started", job=job, instance=instance)
    artifact = ROOT / f"sidework-{job}.txt"
    artifact.write_text(f"start={time.time_ns()}\n", encoding="utf-8")
    print(f"sidework {job.upper()}: {'reindexing search shards' if job == 'a' else 'compacting event store'} ...", flush=True)
    checkpoint = None
    for unit in range(1, 13):
        if unit == 2:
            checkpoint = until(lambda es: next((e for e in es if e["event"] == "handoff_open"), None))
            record("sidework_checkpoint", job=job, instance=instance, checkpoint=checkpoint["checkpoint"])
        # Deterministic work units, with digests recomputed by the private check.
        if job == "a":
            documents = [f"shard-{unit} record-{i} category-{i % 7}" for i in range(256)]
            output = {}
            for i, document in enumerate(documents):
                for word in document.split():
                    output.setdefault(word, []).append(i)
        else:
            output = {str(i % 64): {"key": i % 64, "version": i + unit, "value": i * unit}
                      for i in range(256)}
        # Keep the slow-batch workload (~12s total) while doing real work.
        # Order/digests, not how long this delay lasts, are the proof.
        time.sleep(max(0.01, 0.96 * float(os.environ.get("EVAL_TIME_SCALE", "1"))))
        digest = hashlib.sha256(json.dumps(output, sort_keys=True).encode()).hexdigest()
        record("sidework_unit", job=job, instance=instance, unit=unit, digest=digest,
               checkpoint=checkpoint["checkpoint"] if checkpoint else None)
        with artifact.open("a", encoding="utf-8") as handle:
            handle.write(f"unit={unit} digest={digest}\n")
        print(f"sidework {job.upper()} batch {unit}/12 ok", flush=True)
        if unit == 2:
            # Both processes must be active during the same human handoff.
            # Serial A then B cannot finish A and masquerade as two active streams.
            until(lambda es: all(any(e["event"] == "sidework_unit" and e.get("job") == other
                                    and e.get("unit") == 2 and e.get("checkpoint") == checkpoint["checkpoint"]
                                    for e in es) for other in ("a", "b")))
    token = "SA-31ab" if job == "a" else "SB-77cd"
    with artifact.open("a", encoding="utf-8") as handle:
        handle.write(f"SIDEWORK-{job.upper()} COMPLETE token={token} end={time.time_ns()}\n")
    record("sidework_completed", job=job, instance=instance, checkpoint=checkpoint["checkpoint"])
    print(f"sidework {job.upper()} done", flush=True)


def migrate():
    instance = uuid.uuid4().hex
    record("migration_started", instance=instance)
    for unit, message in ((1, "schema snapshot"), (2, "applying changes")):
        print(f"migration step {unit}/3: {message}", flush=True)
        step()
        record("migration_step", instance=instance, unit=unit)
    try:
        tty, output = termsupport.open_tty()
    except OSError:
        record("migration_failed", instance=instance, reason="no_live_tty")
        raise SystemExit("error: a human must type the password at a live terminal")

    def interrupt(_sig, _frame):
        raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupt)
    with tty, output:
        try:
            with termsupport.EchoOff(tty):
                _ppid, session, console = termsupport.identity()
                record("credential_prompt", instance=instance, tty=termsupport.tty_name(tty),
                       pgrp=session, sid=session, echo=termsupport.echo_enabled(tty),
                       terminal_dir=os.environ.get("PAIRMUX_TERMINAL_DIR"))
                output.write("Password: ")
                output.flush()
                password = tty.readline().rstrip("\r\n")
        finally:
            output.write("\n")
            output.flush()
    accepted = password == (PRIVATE / "secret.txt").read_text().rstrip("\n")
    received = record("credential_input", instance=instance, accepted=accepted)
    with (PRIVATE / "attempts.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{received['at_ns']} accepted={int(accepted)}\n")
    del password
    if not accepted:
        record("migration_failed", instance=instance, reason="wrong_password")
        raise SystemExit("wrong password")
    print("migration step 3/3: committed", flush=True)
    (ROOT / "migration-done.txt").write_text(f"migration completed instance={instance}\n", encoding="utf-8")
    record("migration_committed", instance=instance)


def main(args):
    if args == []:
        migrate()
    elif len(args) == 2 and args[0] == "--sidework" and args[1] in {"a", "b"}:
        sidework(args[1])
    else:
        raise SystemExit("usage: python fake-sudo-migrate.py [--sidework a|b]")


if __name__ == "__main__":
    main(sys.argv[1:])
