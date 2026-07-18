#!/usr/bin/env bash
# Background web-server fixture for eval S08. Chooses a free port, records it, and serves,
# logging each request line (e.g. "GET / HTTP/1.1" 200) to its own output.
set -u
port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
echo "$port" > port.txt
echo "PORT=$port"
exec python3 -m http.server "$port" --bind 127.0.0.1
