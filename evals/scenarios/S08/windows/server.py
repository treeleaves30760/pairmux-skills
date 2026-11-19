"""Background web-server fixture for eval S08 (Windows twin of server.sh). Chooses a free port,
records it, and serves, logging each request line (e.g. "GET / HTTP/1.1" 200) to its own output."""
import runpy
import socket
import sys

probe = socket.socket()
probe.bind(("127.0.0.1", 0))
port = probe.getsockname()[1]
probe.close()
with open("port.txt", "w", encoding="utf-8", newline="\n") as handle:
    handle.write(f"{port}\n")
print(f"PORT={port}", flush=True)
# Like `exec python3 -m http.server PORT --bind 127.0.0.1`, in this same process.
sys.argv = ["http.server", str(port), "--bind", "127.0.0.1"]
runpy.run_module("http.server", run_name="__main__", alter_sys=True)
