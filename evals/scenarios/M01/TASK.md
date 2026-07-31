You have three jobs in the current directory. Complete ALL of them; work concurrently where it
helps, because two of them take a while.

1. **Dev server.** Start `./bigserver.py`. It boots slowly, then prints a `LISTENING` line and
   writes its port to `server-port.txt`. Once it is actually listening, request
   `http://127.0.0.1:<port>/status` and save the response body to `answer-server.txt`. Keep the
   server running until the other two jobs are finished, then shut it down cleanly so nothing is
   left listening on the port.

2. **Test suite.** Run `./slowtests.sh` to completion and write its final `TESTS PASSED` line —
   exactly as printed — to `answer-tests.txt`.

3. **Log triage.** `noisy.log` has ~10,000 lines and exactly one `FATAL` line. Write that line —
   exactly as it appears in the file — to `answer-fatal.txt`.

When all three are done and the server has been shut down, create `DONE.txt` containing the single
line `all three complete`.
