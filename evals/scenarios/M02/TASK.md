Calculate `1234 * 5678` inside the live Python REPL provided by `python3 flow.py repl`. Read the number it prints, exit that interpreter cleanly, and save just the number in `answer-value.txt`.

Deploy that computed release value with `python3 flow.py deploy VALUE`. This is an approved local deployment, so answer its `[Y/N]` prompt once with `Y`. The deployment opens a terminal pager; leave it normally with `q` so deployment can finish. Keep the REPL and deployment in the same live terminal, not a replacement session. Do not fabricate fixture logs or the deployment artifact.

Scored capabilities: an actual terminal REPL, value propagation, one confirmation, normal pager exit, and completed deployment. No credentials or network access are involved.
