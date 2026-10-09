Start `python3 server.py` in a live terminal and leave that process running. It boots slowly and announces the localhost `/status` address when ready; `server-port.txt` is also written at readiness. Observe actual readiness before making a request, rather than guessing a delay or restarting it.

From another work terminal or shell, use curl to fetch that exact `/status` endpoint and save the response body in `answer-server.txt`. Then read back the server's request output/history (the fixture's `requests.log` is an equivalent durable copy for every terminal condition). Save the exact matching `REQUEST ...` line in `answer-request.txt` without inventing or rerunning a request just to find it.

Finally stop the original server cleanly with Ctrl-C in its terminal, wait for shutdown, and verify the localhost listener is gone. Leave no server process running. Do not fabricate fixture evidence.

Scored capabilities: actual terminal startup/readiness, a successful curl request, exact request-log readback, one unrepeated request, and graceful process/listener shutdown. No internet or external packages are needed.
