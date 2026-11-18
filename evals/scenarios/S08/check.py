#!/usr/bin/env python3
"""S08 check. Pass = the client got a 200 AND the server logged the request — proving two terminals
cooperated (server running in one, request driven from another, journal read back)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evallib  # noqa: E402

SCEN_DIR = evallib.scenario_dir(__file__)
TRANSCRIPT = sys.argv[1] if len(sys.argv) > 1 else ""
evallib.load_env(scen_dir=SCEN_DIR)
CLIENT = evallib.fixture_name("hit.sh")

if not evallib.any_journal_has("HTTP-STATUS=200"):
    evallib.fail(f"the client never got a 200 from the server ({CLIENT} did not succeed)")

if not evallib.any_journal_has('"GET / HTTP/1.1" 200'):
    evallib.fail("the server never logged the request (was the server actually running in a terminal?)")

if not evallib.runner_trace_proves("S08"):
    evallib.fail("runner-owned proxy trace does not prove distinct server/client terminals plus "
                 "server journal readback")

if not evallib.issued_requires(TRANSCRIPT, r"GET / HTTP/1[.]1.*200"):
    evallib.fail("agent did not report the server's GET / HTTP/1.1 request line and 200 status")

evallib.passed("server + client cooperated across two terminals and the request was logged")
