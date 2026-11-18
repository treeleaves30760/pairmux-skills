"""Client fixture for eval S08 (Windows twin of hit.sh). Sends one request to the server started by
server.py and prints its status like `curl -w 'HTTP-STATUS=%{http_code}'`."""
from pathlib import Path
import urllib.error
import urllib.request

port = Path("port.txt").read_text(encoding="utf-8").strip()
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=30) as response:
        response.read()
        status = response.status
except urllib.error.HTTPError as error:
    status = error.code
except OSError:
    status = 0
print(f"HTTP-STATUS={status:03d}", flush=True)
