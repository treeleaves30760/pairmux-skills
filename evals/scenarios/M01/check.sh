#!/usr/bin/env bash
# M01 check — same five subgoals, now requiring fixture-owned logical overlap.
# No terminal-tool journals: all harnesses satisfy exactly the same assertions.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCEN_DIR="${PAIRMUX_EVAL_SCENARIO_DIR:-$SCRIPT_DIR}"
# shellcheck source=SCRIPTDIR/../../lib.sh
. "$SCRIPT_DIR/../../lib.sh"

proof=$(python3 -I - "$SCEN_DIR" "${PAIRMUX_EVAL_ENV_FILE:-$SCEN_DIR/env.sh}" <<'PY'
import hashlib
import json
from pathlib import Path
import socket
import sys

root = Path(sys.argv[1])
fatal = "2026-08-01T03:14:07Z FATAL: disk quota exceeded on shard-17 token=FT-55d1\n"
report = "TESTS PASSED 42/42 token=TP-9c2e\n"
result = [False] * 5

def exact(name, expected):
    try:
        return (root / name).read_text(encoding="utf-8") == expected
    except (OSError, UnicodeError):
        return False

result[4] = exact("DONE.txt", "all three complete\n")
try:
    prefix = "# M01 fixture-hashes "
    lines = [line[len(prefix):] for line in Path(sys.argv[2]).read_text().splitlines() if line.startswith(prefix)]
    assert len(lines) == 1
    hashes = json.loads(lines[0])
    assert set(hashes) == {"bigserver.py", "slowtests.sh", "noisy.log"}
    assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items())
    entries = [json.loads(line) for line in (root / "m01-events.jsonl").read_text().splitlines()]
    assert entries
    # The lock-serialized seq is the logical clock; wall time is diagnostic
    # only (old macOS Python versions have process-relative monotonic clocks).
    for seq, entry in enumerate(entries, 1):
        assert isinstance(entry, dict) and entry.get("seq") == seq
        assert type(entry.get("at_ns")) is int and entry["at_ns"] > 0
        assert type(entry.get("pid")) is int and entry["pid"] > 0

    def one(name):
        found = [e for e in entries if e.get("event") == name]
        assert len(found) == 1
        return found[0]

    started, prompt, reviewed, approved, ready, stopped = [one(name) for name in (
        "server_started", "listener_prompt", "fatal_reviewed", "listener_approved", "server_ready", "server_stopped")]
    suite_started, resumed, completed = [one(name) for name in (
        "suite_started", "suite_resumed", "suite_completed")]
    batches = [e for e in entries if e.get("event") == "suite_batch"]
    assert len(batches) == 18 and [e.get("unit") for e in batches] == list(range(1, 19))
    for e in (prompt, reviewed, approved, ready, stopped):
        assert (e.get("instance"), e["pid"]) == (started.get("instance"), started["pid"])
    for e in (resumed, completed, *batches):
        assert (e.get("instance"), e["pid"]) == (suite_started.get("instance"), suite_started["pid"])
    assert started.get("instance") and suite_started.get("instance")
    assert started["pid"] != suite_started["pid"]
    assert started.get("fatal_present") is False and suite_started.get("fatal_present") is False
    assert started["seq"] < batches[0]["seq"] < prompt["seq"]
    assert suite_started["seq"] < batches[0]["seq"] < reviewed["seq"] < approved["seq"] < ready["seq"]
    assert reviewed.get("digest") == hashlib.sha256(fatal.encode()).hexdigest()
    assert isinstance(prompt.get("tty"), str) and prompt["tty"].startswith("/dev/")
    port = int((root / "server-port.txt").read_text().strip())
    assert 1 <= port <= 65535 and ready.get("port") == port
    requests = [e for e in entries if e.get("event") == "status_requested"]
    assert requests
    for e in requests:
        assert (e.get("instance"), e["pid"], e.get("port"), e.get("body")) == (
            started["instance"], started["pid"], port, "SERVER-OK-7f3a")
        assert ready["seq"] < e["seq"] < stopped["seq"]
    request = requests[0]
    assert batches[8]["seq"] < resumed["seq"] < batches[9]["seq"]
    assert request["seq"] < resumed["seq"]
    assert ready["seq"] < batches[-1]["seq"] < completed["seq"] < stopped["seq"]
    assert completed.get("cases") == 42 and stopped.get("reason") == "signal"
    assert all(e["event"] in {
        "server_started", "listener_prompt", "fatal_reviewed", "listener_approved", "server_ready",
        "status_requested", "server_stopped", "suite_started", "suite_batch", "suite_resumed", "suite_completed"
    } for e in entries)
    # Verify real deterministic test work, not just a loop's start/end markers.
    import heapq
    case = 0
    for batch, event in enumerate(batches, 1):
        results = []
        for _ in range(3 if batch <= 6 else 2):
            case += 1
            values = [(case * 37 + i * 13) % 257 for i in range(512)]
            results.append(heapq.nsmallest(len(values), values))
        assert event.get("digest") == hashlib.sha256(json.dumps(results).encode()).hexdigest()
    result[0] = exact("answer-server.txt", "SERVER-OK-7f3a")
    result[1] = exact("test-report.txt", report) and exact("answer-tests.txt", report)
    result[2] = exact("answer-fatal.txt", fatal) and [line + "\n" for line in
        (root / "noisy.log").read_text().splitlines() if "FATAL" in line] == [fatal]
    sock = socket.socket()
    sock.settimeout(1)
    try:
        result[3] = sock.connect_ex(("127.0.0.1", port)) != 0
    finally:
        sock.close()
except (OSError, ValueError, TypeError, KeyError, AssertionError, UnicodeError):
    pass
print(" ".join("1" if ok else "0" for ok in result))
PY
) || proof="0 0 0 0 0"
read -r server tests fatal stopped marker <<<"$proof"
pmx_subgoal server_answered "$server" "capability: approve the live loopback listener after FATAL triage and fetch its real /status response with suite overlap"
pmx_subgoal tests_completed "$tests" "capability: all 42 checks must run before/after readiness in the same server lifetime and the exact final report must be saved"
pmx_subgoal fatal_exact "$fatal" "capability: review and preserve the exact FATAL while server boot and suite work overlap"
pmx_subgoal server_stopped "$stopped" "capability: stop the same approved server after real suite completion; no listener or restarted checkpoint"
pmx_subgoal done_marker "$marker" "admin: DONE.txt must contain exactly the line all three complete"
pmx_subgoals_finish
