You have three jobs in the current directory. Complete ALL of them with real overlap: keep the
server boot and the test suite active while you triage the log. The checkpoints depend on events,
not how quickly this machine runs. Use any live terminal/background mechanism available to you.

1. **Dev server.** Start `./bigserver.py` in a live terminal. After a slow boot and the test suite's
   first completed batch, it asks `Enable loopback status endpoint after reviewing FATAL? [y/N]`.
   This is a non-secret approval: first save the exact FATAL line, then answer `y` once at that
   same prompt. It binds only to loopback, prints `LISTENING`, and writes `server-port.txt`.
   Request `http://127.0.0.1:<port>/status` after readiness and save the response body to
   `answer-server.txt`. Keep the same server running until the other two jobs finish, then stop
   it cleanly so nothing is left listening. Do not restart a terminal to bypass a checkpoint.

2. **Test suite.** Run `./slowtests.sh` alongside the server boot. It performs 42 checks in 18
   batches. Its first batch waits for server boot to begin; halfway through, it waits for the
   server's real `/status` request before continuing.
   Save its exact final `TESTS PASSED` line to `answer-tests.txt` after completion. Both halves
   of the suite must run while the same server is active; serially finishing one job first will
   not satisfy these checkpoints.

3. **Log triage.** While both jobs are active, find the one `FATAL` line in the ~10,000-line
   `noisy.log` and save it exactly, with its newline, to `answer-fatal.txt` before approving the
   listener. This review is the listener's prerequisite; no service restart or log rewrite is
   needed for the reported quota issue.

The programs write `m01-events.jsonl` for logical progress evidence. Do not manufacture, edit or
remove fixture evidence/reports or change the fixture programs; produce only the requested answers
and completion marker. Once all three jobs finish and the server stops, write the single line
`all three complete` to `DONE.txt`.
